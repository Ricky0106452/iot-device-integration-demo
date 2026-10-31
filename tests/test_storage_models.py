"""統一 readings、收據約束與 migration metadata。"""
import os
from pathlib import Path
import unittest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from storage.database import create_db_engine
from storage.models import Device, MeasurementPoint, PointReading, ReceivedMessage

ROOT=Path(__file__).resolve().parents[1]


def upgrade_database(engine):
    config=Config(str(ROOT/"alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"]=connection
        command.upgrade(config,"head")


class StorageMetadataTests(unittest.TestCase):
    def test_initial_migration_is_recorded(self):
        scripts=ScriptDirectory.from_config(Config(str(ROOT/"alembic.ini")))
        self.assertIsNone(scripts.get_revision("0001").down_revision)

    def test_only_one_reading_table_and_no_snapshot_or_payload_columns(self):
        self.assertEqual(set(Device.metadata.tables),{"devices","measurement_points","readings","source_bindings","received_messages"})
        self.assertIsNone(PointReading.__table__.c.value.type.scale)
        self.assertNotIn("content",ReceivedMessage.__table__.columns)
        self.assertNotIn("destinations",ReceivedMessage.__table__.columns)
        self.assertEqual([c.name for c in PointReading.__table__.primary_key],["point_id","receipt_id"])

    def test_platform_names_are_bounded_and_unused_model_code_removed(self):
        self.assertEqual(str(Device.__table__.c.name.type), "VARCHAR(100)")
        self.assertEqual(str(MeasurementPoint.__table__.c.name.type), "VARCHAR(100)")
        self.assertNotIn("model_code", Device.__table__.columns)

    def test_point_values_reference_receipt_and_platform_point(self):
        self.assertEqual({fk.name for fk in PointReading.__table__.foreign_key_constraints},
                         {"fk_readings_point","fk_readings_receipt"})
        self.assertTrue(PointReading.__table__.c.acquired_at.type.timezone)
        self.assertTrue(PointReading.__table__.c.received_at.type.timezone)


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"),"未設定測試資料庫")
class PostgresSchemaTests(unittest.TestCase):
    def test_migrated_database_has_no_snapshot_or_parallel_reading_table(self):
        engine=create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        try:
            upgrade_database(engine)
            tables=inspect(engine).get_table_names()
            self.assertNotIn("telemetry_readings",tables)
            self.assertNotIn("mapped_point_readings",tables)
            self.assertIn("readings",tables)
            self.assertIn("ix_readings_receipt",{item["name"] for item in inspect(engine).get_indexes("readings")})
        finally:
            engine.dispose()
