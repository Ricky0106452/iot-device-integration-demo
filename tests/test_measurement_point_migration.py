"""只在明確命名的臨時 DB 驗證感測點 migration 與歷史回填。"""
from decimal import Decimal
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from storage.database import create_db_engine


@unittest.skipUnless(os.environ.get("IOT_MIGRATION_TEST_DATABASE_URL"), "未設定獨立 migration 測試庫")
class MeasurementPointMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_db_engine(os.environ["IOT_MIGRATION_TEST_DATABASE_URL"])
        with cls.engine.connect() as connection:
            name = connection.execute(text("SELECT current_database()")).scalar_one()
        if not name.startswith("okgo_points_check_"):
            cls.engine.dispose()
            raise RuntimeError("migration 測試只允許 okgo_points_check_ 開頭的自建臨時庫")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)
        self.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        self.config.attributes["connection"] = self.connection
        # 所有 DDL 都在外層交易中；每個方法結束回滾，不接觸使用者 DB。
        command.downgrade(self.config, "base")
        command.upgrade(self.config, "0001")
        self.ids = [uuid4(), uuid4()]
        for device, message, voltage, current, energy in [
            ("migration-a", self.ids[0], "230.1", "10.01", 70000),
            ("migration-b", self.ids[1], "6553.5", "655.35", 4294967295),
        ]:
            self.connection.execute(text("""
                INSERT INTO telemetry_readings
                (device_id, message_id, schema_version, gateway_id, acquired_at, received_at,
                 raw_registers, voltage_v, current_a, power_w, energy_wh)
                VALUES (:device, :message, 1, 'test-gateway', '2026-10-23T00:00:00Z',
                        '2026-10-23T00:00:01Z', ARRAY[2301,1001,2300,1,4464],
                        :voltage, :current, 2300, :energy)
            """), dict(device=device, message=message, voltage=Decimal(voltage),
                       current=Decimal(current), energy=energy))
        command.upgrade(self.config, "0002")

    def test_backfill_preserves_all_source_values_and_times(self):
        snapshots = self.connection.execute(text("SELECT * FROM telemetry_readings ORDER BY device_id")).mappings().all()
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM devices")).scalar_one(), 2)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM measurement_points")).scalar_one(), 8)
        for row in snapshots:
            self.assertEqual(row["model_code"], "SIM-POWER-01")
            self.assertEqual(row["source_data"]["raw_registers"], row["raw_registers"])
            values = self.connection.execute(text("""
                SELECT p.code, r.value, r.acquired_at, r.received_at
                FROM readings r JOIN measurement_points p ON p.point_id = r.point_id
                WHERE r.device_id = :device AND r.message_id = :message
            """), dict(device=row["device_id"], message=row["message_id"])).mappings().all()
            self.assertEqual(len(values), 4)
            for value in values:
                self.assertEqual(value["value"], row[value["code"]])
                self.assertEqual(Decimal(str(row["source_data"]["measurement"][value["code"]])),
                                 value["value"])
                self.assertEqual(value["acquired_at"], row["acquired_at"])
                self.assertEqual(value["received_at"], row["received_at"])

    def test_repeated_upgrade_does_not_duplicate_backfill(self):
        command.upgrade(self.config, "head")
        command.upgrade(self.config, "head")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings")).scalar_one(), 8)

    def test_constraints_reject_cross_device_and_duplicate_values(self):
        row = self.connection.execute(text("SELECT * FROM readings WHERE device_id='migration-a' LIMIT 1")).mappings().one()
        statement = text("""INSERT INTO readings
            (point_id, device_id, message_id, acquired_at, received_at, value)
            VALUES (:point_id, :device_id, :message_id, :acquired_at, :received_at, :value)""")
        for change in [{}, {"device_id": "migration-b", "message_id": self.ids[1]},
                       {"message_id": uuid4()}]:
            with self.subTest(change=change), self.assertRaises(IntegrityError):
                with self.connection.begin_nested():
                    self.connection.execute(statement, {**row, **change})
        with self.assertRaises(IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(text("UPDATE measurement_points SET resolution=0"))
        self.assertIn("ix_readings_point_time", [i["name"] for i in inspect(self.connection).get_indexes("readings")])

    def test_downgrade_and_upgrade_preserve_legacy_snapshots(self):
        command.downgrade(self.config, "0001")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM telemetry_readings")).scalar_one(), 2)
        command.upgrade(self.config, "0002")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings")).scalar_one(), 8)

    def test_non_power_device_blocks_downgrade(self):
        self.connection.execute(text("""INSERT INTO devices VALUES
            ('water-001', '水表', 'SIM-WATER-01')"""))
        with self.assertRaisesRegex(RuntimeError, "拒絕退版"):
            command.downgrade(self.config, "0001")
        self.assertEqual(self.connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0002")


if __name__ == "__main__":
    unittest.main()
