"""補送確認與採集隔離；測試真實 SQLite，不依賴外部 Broker。"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock

from gateway.mqtt_publish import PublishError
from gateway.outbox import Outbox
from gateway.outbox_sender import OutboxSender


class OutboxSenderTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.box = Outbox(Path(self.directory.name) / 'box.db', max_pending=10)
        self.addCleanup(self.box.__exit__, None, None, None)
        self.message = json.loads(Path('docs/mqtt/telemetry.example.json').read_text(encoding='utf-8'))
        self.box.enqueue('saved/topic', self.message)

    def test_unconfirmed_publish_keeps_original_until_success(self):
        publish = Mock(side_effect=[PublishError('publish_unconfirmed', 'timeout'), None])
        sender = OutboxSender(self.box, publish)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertFalse(sender.deliver_next())
            self.assertEqual(self.box.count(), 1)
            self.assertTrue(sender.deliver_next())
        self.assertEqual(self.box.count(), 0)
        self.assertEqual(publish.call_args_list[0], publish.call_args_list[1])
        publish.assert_called_with(self.message, topic='saved/topic')

    def test_record_is_present_while_waiting_for_puback(self):
        def publish(message, **kwargs):
            self.assertEqual(self.box.count(), 1)
        with redirect_stdout(io.StringIO()):
            self.assertTrue(OutboxSender(self.box, publish).deliver_next())
        self.assertEqual(self.box.count(), 0)

    def test_empty_queue_does_not_publish(self):
        self.box.remove(self.box.oldest().sequence)
        publish = Mock()
        self.assertIsNone(OutboxSender(self.box, publish).deliver_next())
        publish.assert_not_called()

    def test_blocked_publish_does_not_block_enqueue(self):
        entered, release, saved = Event(), Event(), Event()
        def publish(message, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test did not release publisher')
        with redirect_stdout(io.StringIO()), OutboxSender(self.box, publish) as sender:
            try:
                self.assertTrue(entered.wait(2))
                def acquire():
                    self.box.enqueue('next/topic', self.message)
                    saved.set()
                producer = Thread(target=acquire)
                producer.start()
                self.assertTrue(saved.wait(1), '網路等待持有 SQLite 鎖，阻塞採集')
                producer.join()
                self.assertEqual(self.box.count(), 2)
            finally:
                release.set()

    def test_sender_exception_stops_main_wait_instead_of_dying_silently(self):
        sender = OutboxSender(self.box, Mock(side_effect=RuntimeError('publisher bug')))
        with self.assertRaisesRegex(RuntimeError, 'publisher bug'):
            with sender:
                sender.wait(2)
        self.assertEqual(self.box.count(), 1)

    def test_failure_wait_is_interruptible(self):
        attempted = Event()
        def publish(*args, **kwargs):
            attempted.set()
            raise PublishError('broker_connection_failed', 'offline')
        with redirect_stderr(io.StringIO()), OutboxSender(self.box, publish, retry_interval=60) as sender:
            self.assertTrue(attempted.wait(2))
        self.assertFalse(sender.thread.is_alive())
        self.assertEqual(self.box.count(), 1)

    def test_failed_local_removal_keeps_message_for_replay(self):
        import sqlite3
        self.box.connection.execute('PRAGMA query_only=ON')
        publish = Mock()
        with self.assertRaises(sqlite3.OperationalError), redirect_stdout(io.StringIO()):
            OutboxSender(self.box, publish).deliver_next()
        publish.assert_called_once()
        self.assertEqual(self.box.count(), 1)
