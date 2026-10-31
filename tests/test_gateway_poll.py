"""多設備循序排程與真實 SQLite 入列；通訊失敗與儲存失敗採取不同處理。"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from gateway.buffering.outbox import Outbox
from gateway.config import GatewaySettings
from gateway.main import main
from gateway.polling import acquire_to_outbox, run_polling
from gateway_test_support import settings_payload


class GatewayPollingTests(unittest.TestCase):
    def settings(self):
        data = settings_payload()
        second = deepcopy(data["devices"][0])
        second.update(device_id="meter-002", unit_id=2, interval_seconds=10)
        data["devices"].append(second)
        return GatewaySettings.model_validate(data)

    def test_device_failure_does_not_block_other_device_and_shared_channel_is_serialized(self):
        settings = self.settings()
        sender = Mock()
        now = [0.0]
        def wait(seconds):
            now[0] += seconds
            if now[0] >= 11:
                raise KeyboardInterrupt
        sender.wait.side_effect = wait
        client = Mock()
        with patch("gateway.polling.acquire_to_outbox", side_effect=[1, 0, 1, 0, 0]) as acquire:
            self.assertEqual(run_polling(settings, Mock(), sender, clock=lambda: now[0],
                                         client_factory=Mock(return_value=client)), 0)
        self.assertEqual([call.args[1].device_id for call in acquire.call_args_list],
                         ["meter-001", "meter-002", "meter-001", "meter-001", "meter-002"])
        self.assertTrue(all(call.args[2] is client for call in acquire.call_args_list))
        client.close.assert_called_once()

    def test_cycle_interval_starts_after_acquisition_finishes(self):
        settings = self.settings().model_copy(update={"devices": self.settings().devices[:1]})
        now = [0.0]
        sender = Mock()
        def acquire(*args):
            now[0] += 3
        sender.wait.side_effect = KeyboardInterrupt
        with patch("gateway.polling.acquire_to_outbox", side_effect=acquire):
            run_polling(settings, Mock(), sender, clock=lambda: now[0], client_factory=Mock())
        sender.wait.assert_called_once_with(5.0)

    def test_unexpected_error_propagates_and_clients_close(self):
        client = Mock()
        with patch("gateway.polling.acquire_to_outbox", side_effect=RuntimeError("bug")), \
             self.assertRaisesRegex(RuntimeError, "bug"):
            run_polling(self.settings(), Mock(), Mock(), client_factory=Mock(return_value=client))
        client.close.assert_called_once()

    def test_successful_points_saved_before_waking_sender_with_new_id_each_cycle(self):
        settings = self.settings()
        readings = [{"code":"temperature", "unit":"degC", "value":"26.5", "acquired_at":"2026-10-31T00:00:00+00:00"}]
        sender = Mock()
        with TemporaryDirectory() as directory, Outbox(Path(directory) / "box.db", max_pending=1) as box, \
             patch("gateway.polling.read_device", return_value=readings), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            def wake():
                self.assertEqual(box.count(), 1)
            sender.wakeup.set.side_effect = wake
            acquire_to_outbox(settings, settings.devices[0], Mock(), box, sender)
            first = box.oldest()
            acquire_to_outbox(settings, settings.devices[0], Mock(), box, sender)
            second = box.oldest()
            self.assertNotEqual(first.message["message_id"], second.message["message_id"])
            self.assertEqual(second.message["readings"], readings)
            self.assertEqual(second.topic, "okgo/demo/v2/devices/meter-001/telemetry")
            self.assertEqual(second.message["schema_version"], 2)
        self.assertEqual(sender.wakeup.set.call_count, 2)

    def test_failed_device_never_enqueues_or_wakes_sender(self):
        box, sender = Mock(), Mock()
        settings = self.settings()
        with patch("gateway.polling.read_device", return_value=[]):
            self.assertEqual(acquire_to_outbox(settings, settings.devices[0], Mock(), box, sender), 1)
        box.enqueue.assert_not_called()
        sender.wakeup.set.assert_not_called()

    def test_storage_failure_is_not_reported_as_buffered(self):
        settings = self.settings()
        with patch("gateway.main.load_settings", return_value=settings), \
             patch("gateway.main.Outbox", side_effect=sqlite3.OperationalError("disk full")), \
             redirect_stderr(io.StringIO()) as errors, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 1)
        self.assertIn("outbox_storage_failed", errors.getvalue())
        self.assertEqual(output.getvalue(), "")
