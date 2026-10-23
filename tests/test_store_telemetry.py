"""S3-03A：真實 PostgreSQL 的單筆入庫、重複與衝突。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from sqlmodel import Session, select

from receiver.models import Telemetry
from storage.database import create_db_engine
from storage.models import TelemetryReading
from storage.telemetry import store_telemetry


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"), "未設定專用資料庫測試連線")
class StoreTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "docs/mqtt/telemetry.example.json"
        self.payload = json.loads(path.read_text(encoding="utf-8"))
        self.payload["message_id"] = str(uuid4())
        self.received_at = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.addCleanup(self.remove_own_rows)

    def remove_own_rows(self):
        # 只刪除本測試隨機 ID 的資料，不清空量測表。
        with Session(self.engine) as session:
            rows = session.exec(select(TelemetryReading).where(
                TelemetryReading.message_id == UUID(self.payload["message_id"]))).all()
            for row in rows:
                session.delete(row)
            session.commit()

    def store(self, payload=None, received_at=None):
        model = Telemetry.model_validate(self.payload if payload is None else payload)
        return store_telemetry(self.engine, model,
                               received_at=self.received_at if received_at is None else received_at)

    def read(self, device_id="meter-001"):
        with Session(self.engine) as session:
            return session.get(TelemetryReading, (device_id, UUID(self.payload["message_id"])))

    def test_committed_reading_is_visible_from_another_connection(self):
        self.assertEqual(self.store(), "stored")
        row = self.read()
        self.assertIsNotNone(row)
        self.assertEqual(row.gateway_id, self.payload["gateway_id"])
        self.assertEqual(row.schema_version, 1)
        self.assertEqual(row.acquired_at, datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        self.assertEqual(row.received_at, self.received_at)
        self.assertEqual(row.raw_registers, [2300, 1000, 2300, 1, 4464])
        self.assertEqual(row.voltage_v, Decimal("230.0"))
        self.assertEqual(row.current_a, Decimal("10.00"))
        self.assertEqual(row.power_w, 2300)
        self.assertEqual(row.energy_wh, 70000)

    def test_duplicate_preserves_first_received_time(self):
        self.store()
        # 相同時間點的不同 UTC 表示與不同接收時間，不應判成衝突。
        self.payload["acquired_at"] = "2026-10-22T01:00:00+00:00"
        self.assertEqual(self.store(received_at=self.received_at + timedelta(seconds=5)), "duplicate")
        self.assertEqual(self.read().received_at, self.received_at)

    def test_changed_source_fields_are_conflicts_and_original_is_preserved(self):
        self.store()
        changes = {
            "gateway_id": "gateway-002",
            "acquired_at": "2026-10-22T01:00:01Z",
            "raw_registers": [2301, 1000, 2300, 1, 4464],
            "measurement": {**self.payload["measurement"], "power_w": 2400},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                altered = {**self.payload, field: value}
                self.assertEqual(self.store(altered), "conflict")
        row = self.read()
        self.assertEqual(row.gateway_id, "gateway-001")
        self.assertEqual(row.power_w, 2300)
        self.assertEqual(row.raw_registers, self.payload["raw_registers"])
        self.assertEqual(row.received_at, self.received_at)

    def test_same_message_id_on_another_device_is_a_new_reading(self):
        self.store()
        self.payload["device_id"] = "meter-002"
        self.assertEqual(self.store(), "stored")
        self.assertIsNotNone(self.read("meter-001"))
        self.assertIsNotNone(self.read("meter-002"))


if __name__ == "__main__":
    unittest.main()
