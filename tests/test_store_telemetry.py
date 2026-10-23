"""S3-03A：真實 PostgreSQL 的單筆入庫、重複與衝突。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlmodel import Session, select

from receiver.models import Telemetry
from storage.database import create_db_engine
from storage.models import Device, MeasurementPoint, PointReading, TelemetryReading
from storage.device_setup import DeviceConfigurationError, initialize_power_device
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
        self.device_id = "store-test-" + uuid4().hex
        self.other_device_id = "store-test-" + uuid4().hex
        self.payload["device_id"] = self.device_id
        self.received_at = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.addCleanup(self.remove_own_rows)
        initialize_power_device(self.engine, self.device_id)
        initialize_power_device(self.engine, self.other_device_id)

    def remove_own_rows(self):
        # 只清理本測試隨機建立的兩台設備，依外鍵順序清除。
        with Session(self.engine) as session:
            for entity in [PointReading, TelemetryReading, MeasurementPoint, Device]:
                rows = session.exec(select(entity).where(
                    entity.device_id.in_([self.device_id, self.other_device_id]))).all()
                for row in rows:
                    session.delete(row)
                session.flush()
            session.commit()

    def store(self, payload=None, received_at=None):
        model = Telemetry.model_validate(self.payload if payload is None else payload)
        return store_telemetry(self.engine, model,
                               received_at=self.received_at if received_at is None else received_at)

    def read(self, device_id=None):
        with Session(self.engine) as session:
            return session.get(TelemetryReading, (device_id or self.device_id, UUID(self.payload["message_id"])))

    def test_committed_reading_is_visible_from_another_connection(self):
        self.assertEqual(self.store(), "stored")
        row = self.read()
        self.assertIsNotNone(row)
        self.assertEqual(row.gateway_id, self.payload["gateway_id"])
        self.assertEqual(row.schema_version, 1)
        self.assertEqual(row.model_code, "SIM-POWER-01")
        self.assertEqual(row.source_data, {"raw_registers": self.payload["raw_registers"],
                                          "measurement": self.payload["measurement"]})
        with Session(self.engine) as session:
            values = session.exec(select(PointReading).where(
                PointReading.device_id == self.device_id)).all()
            points = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id)).all()
            codes = {point.point_id: point.code for point in points}
            self.assertEqual(len(values), 4)
            for value in values:
                self.assertEqual(value.value, Decimal(str(self.payload["measurement"][codes[value.point_id]])))
                self.assertEqual(value.message_id, UUID(self.payload["message_id"]))
                self.assertEqual(value.acquired_at, row.acquired_at)
                self.assertEqual(value.received_at, self.received_at)
        self.assertEqual(row.acquired_at, datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        self.assertEqual(row.received_at, self.received_at)
        self.assertEqual(row.raw_registers, [2300, 1000, 2300, 1, 4464])
        self.assertEqual(row.voltage_v, Decimal("230.0"))
        self.assertEqual(row.current_a, Decimal("10.00"))
        self.assertEqual(row.power_w, 2300)
        self.assertEqual(row.energy_wh, 70000)

    def test_duplicate_preserves_first_received_time(self):
        self.payload["raw_registers"][:2] = [2301, 1001]
        self.payload["measurement"].update(voltage_v=230.1, current_a=10.01)
        self.store()
        # 相同時間點的不同 UTC 表示與不同接收時間，不應判成衝突。
        self.payload["acquired_at"] = "2026-10-22T01:00:00+00:00"
        self.assertEqual(self.store(received_at=self.received_at + timedelta(seconds=5)), "duplicate")
        self.assertEqual(self.read().received_at, self.received_at)
        self.assertEqual(self.read().voltage_v, Decimal("230.1"))
        self.assertEqual(self.read().current_a, Decimal("10.01"))
        with Session(self.engine) as session:
            rows = session.exec(select(PointReading).where(
                PointReading.device_id == self.device_id)).all()
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row.received_at == self.received_at for row in rows))

    def test_changed_source_fields_are_conflicts_and_original_is_preserved(self):
        self.store()
        changes = {
            "gateway_id": "gateway-002",
            "acquired_at": "2026-10-22T01:00:01Z",
            "raw_registers": [2301, 1000, 2300, 1, 4464],
            "measurement": {**self.payload["measurement"], "voltage_v": 230.1, "current_a": 10.01},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                altered = {**self.payload, field: value}
                self.assertEqual(self.store(altered), "conflict")
        row = self.read()
        self.assertEqual(row.gateway_id, "gateway-001")
        self.assertEqual(row.power_w, 2300)
        self.assertEqual(row.voltage_v, Decimal("230.0"))
        self.assertEqual(row.current_a, Decimal("10.00"))
        self.assertEqual(row.raw_registers, self.payload["raw_registers"])
        self.assertEqual(row.received_at, self.received_at)

    def test_initializer_is_idempotent_and_does_not_overwrite_point_settings(self):
        with Session(self.engine) as session:
            before = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id)).all()
            identifiers = {point.code: point.point_id for point in before}
        initialize_power_device(self.engine, self.device_id)
        with Session(self.engine) as session:
            after = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id)).all()
            self.assertEqual({point.code: point.point_id for point in after}, identifiers)

    def test_unconfigured_device_or_missing_point_is_not_stored(self):
        unknown = {**self.payload, "device_id": "unconfigured-" + uuid4().hex}
        with self.assertRaises(DeviceConfigurationError):
            self.store(unknown)
        with Session(self.engine) as session:
            point = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id)).first()
            session.delete(point)
            session.commit()
        with self.assertRaises(DeviceConfigurationError):
            self.store()
        self.assertIsNone(self.read())

    def test_point_insert_failure_rolls_back_snapshot(self):
        def fail_point_insert(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO readings"):
                raise RuntimeError("測試點位寫入失敗")
        event.listen(self.engine, "before_cursor_execute", fail_point_insert)
        try:
            with self.assertRaisesRegex(RuntimeError, "測試點位寫入失敗"):
                self.store()
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_point_insert)
        self.assertIsNone(self.read())
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(PointReading).where(
                PointReading.device_id == self.device_id)).all(), [])

    def test_duplicate_with_missing_point_value_is_an_integrity_error(self):
        self.store()
        with Session(self.engine) as session:
            reading = session.exec(select(PointReading).where(
                PointReading.device_id == self.device_id)).first()
            session.delete(reading)
            session.commit()
        with self.assertRaisesRegex(RuntimeError, "不完整"):
            self.store()

    def test_changed_point_semantics_are_not_silently_reconfigured(self):
        with Session(self.engine) as session:
            point = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id,
                MeasurementPoint.code == "voltage_v")).one()
            point.unit = "kV"
            session.add(point)
            session.commit()
        with self.assertRaises(DeviceConfigurationError):
            initialize_power_device(self.engine, self.device_id)
        with self.assertRaises(DeviceConfigurationError):
            self.store()
        self.assertIsNone(self.read())

    def test_same_message_id_on_another_device_is_a_new_reading(self):
        self.store()
        self.payload["device_id"] = self.other_device_id
        self.assertEqual(self.store(), "stored")
        self.assertIsNotNone(self.read(self.device_id))
        self.assertIsNotNone(self.read(self.other_device_id))


if __name__ == "__main__":
    unittest.main()
