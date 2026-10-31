"""JSON 設定須在任何設備連線或 SQLite 寫入前完整驗證。"""
from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from gateway.config import GatewaySettings, RtuChannel, load_settings
from gateway.main import main
from gateway_test_support import settings_payload


class GatewayConfigTests(unittest.TestCase):
    def test_loads_json_without_changing_working_directory_and_resolves_buffer(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "appsettings.json"
            path.write_text(json.dumps(settings_payload()), encoding="utf-8")
            settings = load_settings(path)
            self.assertEqual(settings.buffer.path, str((Path(directory) / "data/gateway-001-v2-outbox.sqlite3").resolve()))
            self.assertEqual(settings.devices[0].points[0].register_count, 1)

    def test_both_shipped_settings_files_and_multi_device_example_validate(self):
        for path in ["appsettings.json", "config/gateway.docker.json", "config/gateway.multi-device.example.json"]:
            with self.subTest(path=path):
                self.assertIsInstance(load_settings(path), GatewaySettings)
        self.assertIsInstance(load_settings("config/gateway.multi-device.example.json").channels[1], RtuChannel)

    def test_invalid_settings_rejected(self):
        mutations = [
            lambda d: d.update(unknown=True),
            lambda d: d["devices"][0].update(channel_id="missing"),
            lambda d: d["devices"].append(deepcopy(d["devices"][0])),
            lambda d: d["channels"].append(deepcopy(d["channels"][0])),
            lambda d: d["channels"].append(dict(d["channels"][0], channel_id="duplicate-endpoint")),
            lambda d: d["devices"][0]["points"].append(deepcopy(d["devices"][0]["points"][0])),
            lambda d: d["devices"][0].update(unit_id=0),
            lambda d: d["devices"][0].update(unit_id=True),
            lambda d: d["devices"][0].update(interval_seconds=0),
            lambda d: d["devices"][0].update(interval_seconds=float("inf")),
            lambda d: d["devices"][0].update(points=[]),
            lambda d: d["channels"][0].update(port="502"),
            lambda d: d["channels"][0].update(protocol="opcua"),
            lambda d: d["devices"][0]["points"][0].update(address=65535, data_type="float32"),
            lambda d: d["devices"][0]["points"][0].update(scale="NaN"),
            lambda d: d["devices"][0]["points"][0].update(scale="invalid"),
            lambda d: d["devices"][0]["points"][0].update(scale="0"),
            lambda d: d["devices"][0]["points"][0].update(data_type="string"),
            lambda d: d["mqtt"].update(topic_prefix="okgo/+/v2"),
            lambda d: d["mqtt"].update(topic_prefix="okgo/demo/v1"),
            lambda d: d["mqtt"].update(password="secret"),
            lambda d: d["buffer"].update(path=":memory:"),
            lambda d: d["buffer"].update(max_pending=0),
        ]
        for index, mutate in enumerate(mutations):
            data = settings_payload()
            mutate(data)
            with self.subTest(case=index), self.assertRaises(ValidationError):
                GatewaySettings.model_validate(data)

    def test_duplicate_unit_on_same_channel_rejected(self):
        data = settings_payload()
        data["devices"].append(dict(data["devices"][0], device_id="meter-002"))
        with self.assertRaises(ValidationError):
            GatewaySettings.model_validate(data)

    def test_duplicate_json_keys_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "appsettings.json"
            path.write_text('{"gateway_id":"a","gateway_id":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重複"):
                load_settings(path)

    def test_config_errors_do_not_open_outbox_or_expose_password(self):
        data = settings_payload()
        data["mqtt"].update(password="do-not-log-this", port="invalid")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "appsettings.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch("gateway.main.Outbox") as box, redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(path), 1)
            box.assert_not_called()
            self.assertNotIn("do-not-log-this", output.getvalue())
            self.assertIn("configuration_failed", output.getvalue())

    def test_missing_config_fails(self):
        with TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            self.assertEqual(main(Path(directory) / "missing.json"), 1)

    def test_main_uses_only_loaded_settings(self):
        settings = load_settings()
        with patch("gateway.main.load_settings", return_value=settings), \
             patch("gateway.main.Outbox") as box, patch("gateway.main.OutboxSender") as sender, \
             patch("gateway.main.run_polling", return_value=0) as poll:
            self.assertEqual(main(), 0)
            self.assertEqual(box.call_args.kwargs["max_pending"], settings.buffer.max_pending)
            self.assertEqual(sender.call_args.kwargs["retry_interval"], settings.buffer.retry_interval_seconds)
            self.assertEqual(poll.call_args.args[0], settings)
