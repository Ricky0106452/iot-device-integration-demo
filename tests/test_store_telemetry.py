"""舊 v1 相容轉接也只寫統一 readings 與指紋收據，不重建快照。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from sqlalchemy import delete, event, inspect
from sqlmodel import Session, select

from receiver.models import Telemetry
from storage.database import create_db_engine
from storage.device_setup import DeviceConfigurationError, initialize_power_device
from storage.models import Device, MeasurementPoint, PointReading, ReceivedMessage
from storage.telemetry import store_telemetry
from test_storage_models import upgrade_database


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"),"未設定測試資料庫")
class StoreTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        upgrade_database(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.payload=json.loads((Path(__file__).resolve().parents[1]/"docs/mqtt/telemetry.example.json").read_text(encoding="utf-8"))
        self.device_id="legacy-"+uuid4().hex
        self.other_device_id="legacy-"+uuid4().hex
        self.payload.update(device_id=self.device_id,message_id=str(uuid4()))
        self.received_at=datetime(2026,10,23,tzinfo=timezone.utc)
        self.addCleanup(self.cleanup)
        initialize_power_device(self.engine,self.device_id)
        initialize_power_device(self.engine,self.other_device_id)

    def cleanup(self):
        ids=[self.device_id,self.other_device_id]
        with Session(self.engine) as session:
            session.execute(delete(PointReading).where(PointReading.device_id.in_(ids)))
            session.execute(delete(ReceivedMessage).where(ReceivedMessage.source_device_id.in_(ids)))
            session.execute(delete(MeasurementPoint).where(MeasurementPoint.device_id.in_(ids)))
            session.execute(delete(Device).where(Device.device_id.in_(ids)))
            session.commit()

    def store(self,payload=None,received_at=None):
        return store_telemetry(self.engine,Telemetry.model_validate(payload or self.payload),received_at=received_at or self.received_at)

    def receipt(self,device_id=None):
        with Session(self.engine) as session:
            return session.exec(select(ReceivedMessage).where(ReceivedMessage.source_device_id==(device_id or self.device_id),
                ReceivedMessage.message_id==UUID(self.payload["message_id"]))).first()

    def rows(self):
        with Session(self.engine) as session:
            return session.exec(select(PointReading).where(PointReading.device_id==self.device_id)).all()

    def test_committed_values_exist_without_snapshot_or_payload_copy(self):
        self.assertEqual(self.store(),"stored")
        receipt=self.receipt()
        self.assertEqual(receipt.reading_count,4)
        self.assertEqual(len(receipt.content_hash),64)
        self.assertEqual(len(receipt.readings_hash),64)
        self.assertFalse(hasattr(receipt,"content"))
        self.assertNotIn("telemetry_readings",inspect(self.engine).get_table_names())
        self.assertNotIn("mapped_point_readings",inspect(self.engine).get_table_names())
        self.assertEqual({r.source_code:r.value for r in self.rows()},
                         {key:Decimal(str(value)) for key,value in self.payload["measurement"].items()})

    def test_duplicate_preserves_first_received_time_and_values(self):
        self.store()
        self.assertEqual(self.store(received_at=self.received_at+timedelta(seconds=5)),"duplicate")
        self.assertEqual(self.receipt().received_at,self.received_at)
        self.assertEqual(len(self.rows()),4)

    def test_conflicting_values_do_not_overwrite(self):
        self.store()
        changed={**self.payload,"measurement":{**self.payload["measurement"],"voltage_v":230.1},
                 "raw_registers":[2301,1000,2300,1,4464]}
        self.assertEqual(self.store(changed),"conflict")
        self.assertEqual(next(r for r in self.rows() if r.source_code=="voltage_v").value,Decimal("230.0"))

    def test_unconfigured_device_or_missing_point_is_rejected(self):
        with self.assertRaises(DeviceConfigurationError):
            self.store({**self.payload,"device_id":"unknown-"+uuid4().hex})
        with Session(self.engine) as session:
            point=session.exec(select(MeasurementPoint).where(MeasurementPoint.device_id==self.device_id)).first()
            session.delete(point);session.commit()
        with self.assertRaises(DeviceConfigurationError):
            self.store()
        self.assertIsNone(self.receipt())

    def test_failed_reading_insert_rolls_back_receipt(self):
        def fail(connection,cursor,statement,parameters,context,executemany):
            if statement.startswith("INSERT INTO readings"):
                raise RuntimeError("write failure")
        event.listen(self.engine,"before_cursor_execute",fail)
        try:
            with self.assertRaisesRegex(RuntimeError,"write failure"):
                self.store()
        finally:
            event.remove(self.engine,"before_cursor_execute",fail)
        self.assertIsNone(self.receipt())
        self.assertEqual(self.rows(),[])

    def test_duplicate_with_missing_reading_is_integrity_error(self):
        self.store()
        with Session(self.engine) as session:
            row=session.exec(select(PointReading).where(PointReading.device_id==self.device_id)).first()
            session.delete(row);session.commit()
        with self.assertRaisesRegex(RuntimeError,"不一致"):
            self.store()

    def test_initializer_preserves_point_ids_and_rejects_unit_changes(self):
        with Session(self.engine) as session:
            before={p.code:p.point_id for p in session.exec(select(MeasurementPoint).where(MeasurementPoint.device_id==self.device_id)).all()}
        initialize_power_device(self.engine,self.device_id)
        with Session(self.engine) as session:
            points=session.exec(select(MeasurementPoint).where(MeasurementPoint.device_id==self.device_id)).all()
            self.assertEqual({p.code:p.point_id for p in points},before)
            points[0].unit="wrong";session.add(points[0]);session.commit()
        with self.assertRaises(DeviceConfigurationError):
            initialize_power_device(self.engine,self.device_id)

    def test_same_message_id_from_different_device_is_independent(self):
        self.store()
        self.assertEqual(self.store({**self.payload,"device_id":self.other_device_id}),"stored")
        self.assertIsNotNone(self.receipt(self.device_id))
        self.assertIsNotNone(self.receipt(self.other_device_id))
