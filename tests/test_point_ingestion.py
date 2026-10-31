"""真實 PostgreSQL 的獨立來源映射、交易、去重、重綁與並行接收。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import delete, event, text
from sqlmodel import Session, select

from receiver.config import ReceiverSettings
from receiver.point_models import PointTelemetry
from storage.database import create_db_engine
from storage.device_setup import DeviceConfigurationError
from storage.models import Device, MeasurementPoint, SourceBinding, ReceivedMessage, PointReading
from storage.point_telemetry import store_point_telemetry
from storage.source_mapping import configure_sources
from test_storage_models import upgrade_database
from receiver_test_support import point_message, receiver_payload


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"), "未設定獨立測試資料庫")
class PointIngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        upgrade_database(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.payload = receiver_payload(os.environ["IOT_TEST_DATABASE_URL"], uuid4().hex[:12])
        self.settings = ReceiverSettings.model_validate(self.payload)
        self.message = point_message()
        self.received_at = datetime(2026, 10, 31, 8, 0, 2, tzinfo=timezone.utc)
        self.addCleanup(self.cleanup)
        configure_sources(self.engine, self.settings)

    def cleanup(self):
        with Session(self.engine) as session:
            receipts = select(ReceivedMessage.receipt_id).where(ReceivedMessage.receiver_id == self.settings.receiver_id)
            session.execute(delete(PointReading).where(PointReading.receipt_id.in_(receipts)))
            session.execute(delete(ReceivedMessage).where(ReceivedMessage.receiver_id == self.settings.receiver_id))
            session.execute(delete(SourceBinding).where(SourceBinding.receiver_id == self.settings.receiver_id))
            device_ids = [d.device_id for d in self.settings.platform_devices]
            session.execute(delete(MeasurementPoint).where(MeasurementPoint.device_id.in_(device_ids)))
            session.execute(delete(Device).where(Device.device_id.in_(device_ids)))
            session.commit()

    def store(self, message=None, topic=None, received_at=None):
        return store_point_telemetry(self.engine, PointTelemetry.model_validate(message or self.message),
            receiver_id=self.settings.receiver_id, topic=topic or self.settings.topics[0],
            received_at=received_at or self.received_at)

    def receipts(self):
        with Session(self.engine) as session:
            return session.exec(select(ReceivedMessage).where(ReceivedMessage.receiver_id == self.settings.receiver_id)).all()

    def readings(self):
        with Session(self.engine) as session:
            return session.exec(select(PointReading).join(ReceivedMessage,
                PointReading.receipt_id == ReceivedMessage.receipt_id).where(
                ReceivedMessage.receiver_id == self.settings.receiver_id)).all()

    def target_point(self, code="temp1"):
        with Session(self.engine) as session:
            return session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.settings.platform_devices[0].device_id,
                MeasurementPoint.code == code)).one()

    def test_temp2_maps_to_temp1_without_source_device_registration(self):
        self.assertEqual(self.store(), "stored")
        rows = self.readings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].point_id, self.target_point().point_id)
        self.assertEqual(rows[0].source_code, "temp2")
        self.assertEqual(rows[0].value, Decimal("26.5"))
        self.assertEqual(rows[0].acquired_at, datetime(2026, 10, 31, 8, tzinfo=timezone.utc))
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Device, "sensor-002"))

    def test_topic_gateway_device_and_code_all_participate_in_source_selection(self):
        for field, value in [("gateway_id", "other-gateway"), ("device_id", "other-device")]:
            message = deepcopy(self.message)
            message[field] = value
            self.assertEqual(self.store(message), "unmapped")
        message = deepcopy(self.message)
        message["readings"][0]["code"] = "other-code"
        self.assertEqual(self.store(message), "unmapped")
        self.assertEqual(self.store(topic="other/topic"), "unmapped")
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.readings(), [])

    def test_unbound_points_are_ignored_without_discarding_bound_point(self):
        self.message["readings"].append(dict(self.message["readings"][0], code="unbound", value="99"))
        self.assertEqual(self.store(), "stored")
        self.assertEqual(len(self.readings()), 1)

    def test_unit_mismatch_rejects_without_partial_writes(self):
        for field, value in [("unit", "degF")]:
            message = deepcopy(self.message)
            message["readings"][0][field] = value
            with self.assertRaises(DeviceConfigurationError):
                self.store(message)
            self.assertEqual(self.receipts(), [])
            self.assertEqual(self.readings(), [])

    def test_decimal_value_is_preserved_without_rounding_to_display_resolution(self):
        self.message["readings"][0]["value"] = "26.600000381469727"
        self.assertEqual(self.store(), "stored")
        self.assertEqual(self.readings()[0].value, Decimal("26.600000381469727"))

    def test_duplicate_retains_first_received_time_and_equivalent_representation(self):
        self.assertEqual(self.store(), "stored")
        self.message["readings"][0].update(value="26.500", acquired_at="2026-10-31T16:00:00+08:00")
        self.assertEqual(self.store(received_at=self.received_at+timedelta(seconds=5)), "duplicate")
        self.assertEqual(self.readings()[0].received_at, self.received_at)
        self.assertEqual(len(self.receipts()), 1)

    def test_large_and_subnormal_values_roundtrip_without_numeric_rounding(self):
        for value in ["1" + "0" * 308, "0." + "0" * 333 + "5"]:
            self.message["message_id"] = str(uuid4())
            self.message["readings"][0]["value"] = value
            self.assertEqual(self.store(), "stored")
        self.assertEqual({row.value for row in self.readings()},
                         {Decimal("1e308"), Decimal("5e-334")})

    def test_conflicting_content_does_not_overwrite(self):
        self.store()
        self.message["readings"][0]["value"] = "80.0"
        self.assertEqual(self.store(), "conflict")
        self.assertEqual(self.readings()[0].value, Decimal("26.5"))

    def test_rebind_does_not_redirect_redelivery_but_new_message_uses_new_point(self):
        self.store()
        original = self.target_point().point_id
        self.payload["bindings"][0]["target_point_code"] = "temp-other"
        configure_sources(self.engine, ReceiverSettings.model_validate(self.payload))
        self.assertEqual(self.store(), "duplicate")
        self.assertEqual(self.readings()[0].point_id, original)
        self.message["message_id"] = str(uuid4())
        self.assertEqual(self.store(), "stored")
        self.assertEqual({r.point_id for r in self.readings()}, {original, self.target_point("temp-other").point_id})

    def test_parallel_duplicate_delivery_only_inserts_once(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.store(), range(4)))
        self.assertEqual(results.count("stored"), 1)
        self.assertEqual(results.count("duplicate"), 3)
        self.assertEqual(len(self.readings()), 1)

    def test_reading_failure_rolls_back_received_message(self):
        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO readings"):
                raise RuntimeError("simulated write failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                self.store()
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        self.assertEqual(self.receipts(), [])
        self.assertEqual(self.readings(), [])
        self.assertEqual(self.store(), "stored")

    def test_corrupt_missing_reading_is_not_acknowledgeable_duplicate(self):
        self.store()
        with Session(self.engine) as session:
            session.execute(delete(PointReading).where(PointReading.receipt_id == self.receipts()[0].receipt_id))
            session.commit()
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            self.store()

    def test_point_api_reads_v2_values_from_the_same_readings_table(self):
        from fastapi.testclient import TestClient
        from api.main import create_app
        self.store()
        with TestClient(create_app(database_url=os.environ["IOT_TEST_DATABASE_URL"])) as client:
            response=client.get(f"/points/{self.target_point().point_id}/readings")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["readings"][0]["value"],"26.5")
        self.assertEqual(response.json()["readings"][0]["message_id"],self.message["message_id"])

    def test_same_external_uuid_from_two_sources_can_write_the_same_platform_point(self):
        self.payload["bindings"].append(dict(self.payload["bindings"][0],source_gateway_id="gateway-002"))
        configure_sources(self.engine,ReceiverSettings.model_validate(self.payload))
        self.assertEqual(self.store(),"stored")
        other=deepcopy(self.message)
        other["gateway_id"]="gateway-002"
        other["readings"][0]["value"]="30.0"
        self.assertEqual(self.store(other),"stored")
        values=self.readings()
        self.assertEqual(len(values),2)
        self.assertEqual({row.message_id for row in values},{values[0].message_id})
        self.assertEqual(len({row.receipt_id for row in values}),2)

    def test_configuration_is_idempotent_and_does_not_change_point_id(self):
        first = self.target_point().point_id
        configure_sources(self.engine, self.settings)
        self.assertEqual(self.target_point().point_id, first)

    def test_failed_configuration_replacement_rolls_back_old_bindings(self):
        self.payload["platform_devices"][0]["points"][0]["unit"] = "degF"
        with self.assertRaises(DeviceConfigurationError):
            configure_sources(self.engine, ReceiverSettings.model_validate(self.payload))
        self.assertEqual(self.store(), "stored")
