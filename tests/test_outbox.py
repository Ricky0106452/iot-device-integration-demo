"""SQLite 待送資料的持久性、容量淘汰與交易邊界。"""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from gateway.outbox import Outbox


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'pending.sqlite3'
        self.message = json.loads(Path('docs/mqtt/telemetry.example.json').read_text(encoding='utf-8'))

    def message_with_id(self):
        return dict(self.message, message_id=str(uuid4()))

    def test_reopen_preserves_fifo_topic_id_time_and_values(self):
        first, second = self.message_with_id(), self.message_with_id()
        with Outbox(self.path, max_pending=10) as box:
            box.enqueue('original/topic', first)
            box.enqueue('second/topic', second)
        with Outbox(self.path, max_pending=10) as box:
            item = box.oldest()
            self.assertEqual(item.topic, 'original/topic')
            self.assertEqual(item.message, first)
            box.remove(item.sequence)
            self.assertEqual(box.oldest().message, second)

    def test_capacity_discards_oldest_and_returns_actual_count(self):
        messages = [self.message_with_id() for _ in range(3)]
        with Outbox(self.path, max_pending=2) as box:
            self.assertEqual(box.enqueue('topic', messages[0]), 0)
            self.assertEqual(box.enqueue('topic', messages[1]), 0)
            self.assertEqual(box.enqueue('topic', messages[2]), 1)
            self.assertEqual(box.count(), 2)
            self.assertEqual(box.oldest().message, messages[1])

    def test_failed_insert_rolls_back_capacity_eviction(self):
        with Outbox(self.path, max_pending=1) as box:
            box.enqueue('topic', self.message)
            with closing(sqlite3.connect(self.path)) as conn:
                conn.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON pending BEGIN SELECT RAISE(ABORT, 'disk write rejected'); END")
                conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                box.enqueue('topic', self.message_with_id())
            self.assertEqual(box.count(), 1)
            self.assertEqual(box.oldest().message, self.message)

    def test_old_ack_cannot_remove_new_message_after_eviction(self):
        with Outbox(self.path, max_pending=1) as box:
            box.enqueue('topic', self.message)
            old_sequence = box.oldest().sequence
            newer = self.message_with_id()
            box.enqueue('topic', newer)
            box.remove(old_sequence)
            self.assertEqual(box.oldest().message, newer)

    def test_invalid_json_does_not_evict_saved_data(self):
        with Outbox(self.path, max_pending=1) as box:
            box.enqueue('topic', self.message)
            with self.assertRaises(ValueError):
                box.enqueue('topic', {'number': float('nan')})
            self.assertEqual(box.oldest().message, self.message)

    def test_invalid_capacity_is_rejected(self):
        for value in [0, -1]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Outbox(self.path, max_pending=value)

    def test_invalid_storage_location_fails_instead_of_using_memory(self):
        with self.assertRaises(sqlite3.OperationalError):
            Outbox(Path(self.directory.name), max_pending=10)

    def test_memory_database_cannot_be_used_for_durable_queue(self):
        with self.assertRaises(ValueError):
            Outbox(':memory:', max_pending=10)
