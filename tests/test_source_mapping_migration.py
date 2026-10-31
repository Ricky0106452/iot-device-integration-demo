"""0003 保留歷史點位值、補齊舊資料，移除快照並拒絕有損退版。"""
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect,text

from receiver.models import Telemetry
from storage.database import create_db_engine
from storage.models import Device
from storage.telemetry import store_telemetry


@unittest.skipUnless(os.environ.get("IOT_MIGRATION_TEST_DATABASE_URL"),"未設定獨立 migration DB")
class SourceMappingMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_db_engine(os.environ["IOT_MIGRATION_TEST_DATABASE_URL"])
        self.addCleanup(self.engine.dispose)
        self.connection=self.engine.connect()
        self.addCleanup(self.connection.close)
        if not self.connection.execute(text("SELECT current_database()")).scalar_one().startswith("okgo_points_check_"):
            raise RuntimeError("僅允許測試專用資料庫")
        self.connection.rollback()
        transaction=self.connection.begin()
        self.addCleanup(transaction.rollback)
        self.config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
        self.config.attributes["connection"]=self.connection
        command.upgrade(self.config,"head")
        command.downgrade(self.config,"0002")

    def seed_legacy(self):
        command.downgrade(self.config,"0001")
        self.payload=json.loads((Path(__file__).resolve().parents[1]/"docs/mqtt/telemetry.example.json").read_text(encoding="utf-8"))
        self.payload.update(device_id="migration-legacy",message_id=str(uuid4()))
        self.connection.execute(text("""INSERT INTO telemetry_readings
            (device_id,message_id,schema_version,gateway_id,acquired_at,received_at,raw_registers,
             voltage_v,current_a,power_w,energy_wh)
            VALUES (:device,:message,1,:gateway,:acquired,'2026-10-23T00:00:00Z',ARRAY[2300,1000,2300,1,4464],
                    230.0,10.00,2300,70000)"""),
            {"device":self.payload["device_id"],"message":self.payload["message_id"],
             "gateway":self.payload["gateway_id"],"acquired":self.payload["acquired_at"]})
        command.upgrade(self.config,"0002")

    def test_legacy_values_point_ids_and_times_survive_snapshot_removal(self):
        self.seed_legacy()
        before=self.connection.execute(text("SELECT point_id,message_id,device_id,value,acquired_at,received_at FROM readings ORDER BY point_id")).all()
        command.upgrade(self.config,"head")
        after=self.connection.execute(text("SELECT point_id,message_id,device_id,value,acquired_at,received_at FROM readings ORDER BY point_id")).all()
        self.assertEqual(before,after)
        self.assertNotIn("telemetry_readings",inspect(self.connection).get_table_names())
        self.assertNotIn("mapped_point_readings",inspect(self.connection).get_table_names())
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM received_messages")).scalar_one(),1)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings WHERE receipt_id IS NULL OR source_code IS NULL")).scalar_one(),0)

    def test_redelivery_after_migration_is_duplicate_and_does_not_add_values(self):
        self.seed_legacy()
        command.upgrade(self.config,"head")
        result=store_telemetry(self.connection,Telemetry.model_validate(self.payload),
                               received_at=datetime(2026,10,24,tzinfo=timezone.utc))
        self.assertEqual(result,"duplicate")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings")).scalar_one(),4)

    def test_missing_legacy_readings_are_recovered_from_snapshot_before_drop(self):
        self.seed_legacy()
        self.connection.execute(text("DELETE FROM readings"))
        command.upgrade(self.config,"head")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings")).scalar_one(),4)
        self.assertEqual(self.connection.execute(text("SELECT sum(value) FROM readings")).scalar_one(),Decimal("72540.00"))

    def test_empty_downgrade_is_reversible(self):
        command.upgrade(self.config,"head")
        self.assertNotIn("telemetry_readings",inspect(self.connection).get_table_names())
        command.downgrade(self.config,"0002")
        self.assertIn("telemetry_readings",inspect(self.connection).get_table_names())
        command.upgrade(self.config,"head")

    def test_populated_downgrade_is_rejected_without_erasing_history(self):
        self.seed_legacy()
        command.upgrade(self.config,"head")
        with self.assertRaisesRegex(RuntimeError,"拒絕退版"):
            command.downgrade(self.config,"0002")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM readings")).scalar_one(),4)

    def test_overlong_existing_name_blocks_migration_without_truncating(self):
        for table in ("devices", "measurement_points"):
            with self.subTest(table=table):
                with self.connection.begin_nested() as transaction:
                    self.connection.execute(text("INSERT INTO devices(device_id,name,model_code) VALUES ('long-name','正常名稱','SIM-POWER-01')"))
                    if table == "devices":
                        self.connection.execute(text("UPDATE devices SET name=:name WHERE device_id='long-name'"), {"name":"溫"*101})
                    else:
                        self.connection.execute(text("INSERT INTO measurement_points(point_id,device_id,code,name,unit,resolution) VALUES (:point,'long-name','temperature',:name,'degC',0.1)"),
                                                {"point":uuid4(),"name":"溫"*101})
                    with self.assertRaisesRegex(RuntimeError,"不自動截斷"):
                        command.upgrade(self.config,"head")
                    self.assertEqual(self.connection.execute(text(f"SELECT max(char_length(name)) FROM {table}")).scalar_one(),101)
                    transaction.rollback()

    def test_head_metadata_and_indexes_match_unified_schema(self):
        command.upgrade(self.config,"head")
        self.assertEqual(compare_metadata(MigrationContext.configure(self.connection,opts={"compare_type":True}),Device.metadata),[])
        foreign_keys={item["name"] for item in inspect(self.connection).get_foreign_keys("readings")}
        self.assertEqual(foreign_keys,{"fk_readings_point","fk_readings_receipt"})
        self.assertIn("ix_readings_receipt",{item["name"] for item in inspect(self.connection).get_indexes("readings")})
