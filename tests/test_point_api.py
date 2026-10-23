"""設備／點位探索與點位歷史 API 的 PostgreSQL 驗證。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.main import create_app
from receiver.models import Telemetry
from storage.database import create_db_engine
from storage.device_setup import initialize_power_device
from storage.models import Device, MeasurementPoint, PointReading, TelemetryReading
from storage.telemetry import store_telemetry


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"), "未設定專用資料庫測試連線")
class PointApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["IOT_TEST_DATABASE_URL"]
        cls.engine = create_db_engine(cls.url)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with cls.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.device_id = "point-api-" + uuid4().hex
        self.other_id = "point-api-" + uuid4().hex
        self.addCleanup(self.cleanup_rows)
        initialize_power_device(self.engine, self.device_id)
        initialize_power_device(self.engine, self.other_id)
        self.client = TestClient(create_app(database_url=self.url))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        with Session(self.engine) as session:
            points = session.exec(select(MeasurementPoint).where(
                MeasurementPoint.device_id == self.device_id)).all()
            self.points = {point.code: point.point_id for point in points}

    def cleanup_rows(self):
        with Session(self.engine) as session:
            for entity in [PointReading, TelemetryReading, MeasurementPoint, Device]:
                for row in session.exec(select(entity).where(
                    entity.device_id.in_([self.device_id, self.other_id]))).all():
                    session.delete(row)
                session.flush()
            session.commit()

    def store(self, offset=0, message_id=None, voltage=230.1):
        payload = json.loads((Path(__file__).resolve().parents[1] /
            "docs/mqtt/telemetry.example.json").read_text(encoding="utf-8"))
        payload.update(device_id=self.device_id, message_id=message_id or str(uuid4()),
            acquired_at=(datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(seconds=offset)).isoformat())
        payload["measurement"]["voltage_v"] = voltage
        store_telemetry(self.engine, Telemetry.model_validate(payload),
            received_at=datetime(2026, 10, 23, 1, tzinfo=timezone.utc))
        return payload["message_id"]

    def test_device_discovery_and_pagination(self):
        with Session(self.engine) as session:
            expected = session.exec(select(Device).order_by(Device.device_id)).all()
        response = self.client.get("/devices", params={"limit": 2, "offset": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["device_id"] for row in response.json()],
                         [row.device_id for row in expected[1:3]])
        self.assertEqual(set(response.json()[0]), {"device_id", "name", "model_code"})

    def test_points_are_discoverable_with_name_unit_and_resolution(self):
        response = self.client.get(f"/devices/{self.device_id}/points")
        self.assertEqual(response.status_code, 200)
        points = response.json()
        self.assertEqual([point["code"] for point in points], sorted(self.points))
        voltage = next(point for point in points if point["code"] == "voltage_v")
        self.assertEqual(voltage["unit"], "V")
        self.assertEqual(Decimal(voltage["resolution"]), Decimal("0.1"))
        self.assertEqual(voltage["device_id"], self.device_id)
        self.assertEqual(voltage["point_id"], str(self.points["voltage_v"]))
        page = self.client.get(f"/devices/{self.device_id}/points?limit=1&offset=1").json()
        self.assertEqual(page, points[1:2])

    def test_point_history_uses_acquired_time_and_message_order_with_pagination(self):
        early = self.store(offset=0, voltage=230.1)
        low = self.store(offset=10, message_id="00000000-0000-4000-8000-000000000001", voltage=230.2)
        high = self.store(offset=10, message_id="00000000-0000-4000-8000-000000000002", voltage=230.3)
        url = f"/points/{self.points['voltage_v']}/readings"
        response = self.client.get(url, params={"limit": 2})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["point"]["device_id"], self.device_id)
        self.assertEqual(body["point"]["unit"], "V")
        self.assertEqual([row["message_id"] for row in body["readings"]], [high, low])
        self.assertEqual([row["value"] for row in body["readings"]], ["230.3", "230.2"])
        self.assertNotIn("raw_registers", json.dumps(body))
        self.assertNotIn("source_data", json.dumps(body))
        last = self.client.get(url, params={"limit": 2, "offset": 2}).json()
        self.assertEqual([row["message_id"] for row in last["readings"]], [early])
        for row in body["readings"]:
            self.assertIsNotNone(datetime.fromisoformat(row["acquired_at"].replace("Z", "+00:00")).tzinfo)

    def test_existing_point_without_readings_and_missing_resources(self):
        point_url = f"/points/{self.points['voltage_v']}/readings"
        response = self.client.get(point_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["readings"], [])
        self.assertEqual(self.client.get(f"/points/{uuid4()}/readings").status_code, 404)
        self.assertEqual(self.client.get("/devices/no-such-device/points").status_code, 404)

    def test_invalid_identifiers_and_pagination(self):
        point_url = f"/points/{self.points['voltage_v']}/readings"
        self.assertEqual(self.client.get("/points/not-a-uuid/readings").status_code, 422)
        self.assertEqual(self.client.get("/devices/INVALID/points").status_code, 422)
        for url in ["/devices", f"/devices/{self.device_id}/points", point_url]:
            for params in [{"limit": 0}, {"limit": 1001}, {"offset": -1}]:
                with self.subTest(url=url, params=params):
                    self.assertEqual(self.client.get(url, params=params).status_code, 422)

    def test_different_model_point_metadata_can_be_queried(self):
        # 只驗證資料模型與探索 API，不偽造水表原始快照或硬體整合。
        with Session(self.engine) as session:
            session.add(Device(device_id=self.other_id + "-water", name="測試水表", model_code="TEST-WATER"))
            session.commit()
        water_id = self.other_id + "-water"
        def cleanup_water():
            with Session(self.engine) as session:
                for point in session.exec(select(MeasurementPoint).where(MeasurementPoint.device_id == water_id)).all():
                    session.delete(point)
                session.flush()
                session.delete(session.get(Device, water_id))
                session.commit()
        self.addCleanup(cleanup_water)
        with Session(self.engine) as session:
            session.add(MeasurementPoint(point_id=uuid4(), device_id=water_id,
                code="flow_rate_l_min", name="流量", unit="L/min", resolution=Decimal("0.001")))
            session.commit()
        response = self.client.get(f"/devices/{water_id}/points")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["code"], "flow_rate_l_min")
        self.assertEqual(response.json()[0]["unit"], "L/min")


if __name__ == "__main__":
    unittest.main()
