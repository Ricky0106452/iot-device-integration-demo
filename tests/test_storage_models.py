"""S3-01：資料表型別、唯一鍵與 PostgreSQL 實際行為。"""
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from storage.database import create_db_engine
from storage.models import TelemetryReading


ROOT = Path(__file__).resolve().parents[1]


def upgrade_database(engine):
    """測試也走正式 migration，不以 metadata.create_all 偷建表。"""
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


class StorageMetadataTests(unittest.TestCase):
    def test_initial_migration_is_recorded(self):
        scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        initial = scripts.get_revision("0001")
        self.assertIsNotNone(initial)
        self.assertIsNone(initial.down_revision)

    def test_entity_uses_required_storage_types_and_composite_key(self):
        table = TelemetryReading.__table__
        self.assertEqual([c.name for c in table.primary_key], ["device_id", "message_id"])
        self.assertEqual(str(table.c.energy_wh.type), "BIGINT")
        self.assertTrue(table.c.acquired_at.type.timezone)
        self.assertTrue(table.c.received_at.type.timezone)
        self.assertTrue(all(not column.nullable for column in table.columns))


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"), "未設定專用資料庫測試連線")
class PostgresSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        upgrade_database(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def reading(self, message_id=None):
        return TelemetryReading(
            device_id="test-meter", message_id=message_id or uuid4(), schema_version=1,
            gateway_id="test-gateway",
            acquired_at=datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 10, 23, 0, 1, tzinfo=timezone.utc),
            raw_registers=[65535] * 5,
            voltage_v=Decimal("6553.5"), current_a=Decimal("655.35"),
            power_w=65535, energy_wh=4294967295,
        )

    def test_repeated_upgrade_preserves_existing_data(self):
        row = self.reading()
        key = (row.device_id, row.message_id)
        # 此測試需提交資料以跨連線驗證；結束時只刪除自己建立的那筆。
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
        try:
            upgrade_database(self.engine)
            upgrade_database(self.engine)
            with Session(self.engine) as session:
                stored = session.get(TelemetryReading, key)
                self.assertIsNotNone(stored)
                self.assertEqual(stored.energy_wh, 4294967295)
            inspector = inspect(self.engine)
            self.assertEqual(inspector.get_pk_constraint("telemetry_readings")["constrained_columns"],
                             ["device_id", "message_id"])
        finally:
            with Session(self.engine) as session:
                stored = session.get(TelemetryReading, key)
                if stored is not None:
                    session.delete(stored)
                    session.commit()

    def test_postgres_roundtrip_preserves_max_energy_decimals_array_and_time(self):
        # 測試只 flush，不 commit；離開 Session 後回滾，不留下測試量測。
        with Session(self.engine) as session:
            row = self.reading()
            key = (row.device_id, row.message_id)
            session.add(row)
            session.flush()
            session.expunge_all()
            stored = session.get(TelemetryReading, key)
            self.assertEqual(stored.energy_wh, 4294967295)
            self.assertEqual(stored.voltage_v, Decimal("6553.5"))
            self.assertEqual(stored.current_a, Decimal("655.35"))
            self.assertEqual(stored.raw_registers, [65535] * 5)
            self.assertEqual(stored.acquired_at, row.acquired_at)
            self.assertEqual(stored.received_at, row.received_at)

    def test_postgres_rejects_duplicate_device_and_message_id(self):
        with Session(self.engine) as session:
            message_id = uuid4()
            row = self.reading(message_id)
            session.add(row)
            session.flush()
            session.expunge(row)
            session.add(self.reading(message_id))
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()


if __name__ == "__main__":
    unittest.main()
