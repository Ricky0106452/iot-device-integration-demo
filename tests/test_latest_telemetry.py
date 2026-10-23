"""最新量測 API：真實 PostgreSQL 與 HTTP 路由行為。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.main import create_app
from storage.database import create_db_engine
from storage.models import TelemetryReading


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL"), "未設定專用資料庫測試連線")
class LatestTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 測試可直接對空的專用 DB 執行，不依賴其他測試先建立資料表。
        engine = create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        try:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        finally:
            engine.dispose()

    def setUp(self):
        url = os.environ["IOT_TEST_DATABASE_URL"]
        self.engine = create_db_engine(url)
        self.device_id = f"api-test-{uuid4().hex}"
        self.other_device_id = f"api-test-{uuid4().hex}"
        self.addCleanup(self.cleanup)
        self.client = TestClient(create_app(database_url=url))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def cleanup(self):
        with Session(self.engine) as session:
            rows = session.exec(select(TelemetryReading).where(
                TelemetryReading.device_id.in_([self.device_id, self.other_device_id]))).all()
            for row in rows:
                session.delete(row)
            session.commit()
        self.engine.dispose()

    def add_reading(self, *, device_id=None, acquired_offset=0, received_offset=0, message_id=None):
        acquired = datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(seconds=acquired_offset)
        received = datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(seconds=received_offset)
        row = TelemetryReading(
            device_id=device_id or self.device_id, message_id=message_id or uuid4(),
            schema_version=1, gateway_id="gateway-001", acquired_at=acquired,
            received_at=received, raw_registers=[2301, 1001, 2300, 1, 4464],
            voltage_v=Decimal("230.1"), current_a=Decimal("10.01"),
            power_w=2300, energy_wh=70000,
        )
        key = str(row.message_id)
        with Session(self.engine) as session:
            session.add(row)
            session.commit()
        return key

    def get_latest(self, device_id=None):
        return self.client.get(f"/devices/{device_id or self.device_id}/telemetry/latest")

    def test_latest_uses_acquired_time_and_filters_device(self):
        newest = self.add_reading(acquired_offset=10, received_offset=11)
        self.add_reading(acquired_offset=5, received_offset=20)
        self.add_reading(device_id=self.other_device_id, acquired_offset=30, received_offset=31)
        response = self.get_latest()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message_id"], newest)
        self.assertEqual(response.json()["device_id"], self.device_id)

    def test_same_acquired_time_uses_stable_message_id_order(self):
        low = UUID("00000000-0000-4000-8000-000000000001")
        high = UUID("00000000-0000-4000-8000-000000000002")
        self.add_reading(message_id=high, received_offset=1)
        self.add_reading(message_id=low, received_offset=2)
        self.assertEqual(self.get_latest().json()["message_id"], str(high))
        self.assertEqual(self.get_latest().json()["message_id"], str(high))

    def test_response_preserves_measurement_and_timezone(self):
        message_id = self.add_reading()
        response = self.get_latest()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"schema_version", "message_id", "device_id", "gateway_id",
                                     "acquired_at", "received_at", "raw_registers", "measurement"})
        self.assertEqual(body["message_id"], message_id)
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["gateway_id"], "gateway-001")
        self.assertEqual(body["raw_registers"], [2301, 1001, 2300, 1, 4464])
        self.assertEqual(body["measurement"], {"voltage_v": 230.1, "current_a": 10.01,
                                               "power_w": 2300, "energy_wh": 70000})
        for field in ["acquired_at", "received_at"]:
            parsed = datetime.fromisoformat(body[field].replace("Z", "+00:00"))
            self.assertEqual(parsed, datetime(2026, 10, 23, tzinfo=timezone.utc))

    def test_history_lists_all_devices_with_stable_pagination(self):
        self.add_reading(acquired_offset=10)
        self.add_reading(device_id=self.other_device_id, acquired_offset=20)
        self.add_reading(acquired_offset=5, received_offset=30)
        # 以 DB 全域順序核對頁面，不假設測試庫沒有其他合法資料。
        with Session(self.engine) as session:
            expected = session.exec(select(TelemetryReading).order_by(
                TelemetryReading.acquired_at.desc(), TelemetryReading.device_id.asc(),
                TelemetryReading.message_id.desc())).all()
        actual = []
        for offset in range(0, len(expected), 2):
            response = self.client.get("/telemetry", params={"limit": 2, "offset": offset})
            self.assertEqual(response.status_code, 200)
            page = response.json()
            self.assertLessEqual(len(page), 2)
            actual.extend((item["device_id"], item["message_id"]) for item in page)
        self.assertEqual(actual, [(row.device_id, str(row.message_id)) for row in expected])
        self.assertIn(self.device_id, [device for device, _ in actual])
        self.assertIn(self.other_device_id, [device for device, _ in actual])

    def test_history_empty_page_and_default_query(self):
        response = self.client.get("/telemetry")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        self.assertLessEqual(len(response.json()), 100)
        response = self.client.get("/telemetry", params={"offset": 2147483647})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_history_rejects_invalid_pagination(self):
        for params in [{"limit": 0}, {"limit": 1001}, {"offset": -1}, {"limit": "bad"}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/telemetry", params=params).status_code, 422)

    def test_missing_device_reading_returns_404(self):
        self.assertEqual(self.get_latest().status_code, 404)
        self.assertEqual(self.get_latest().json(), {"detail": "No telemetry found for device"})

    def test_invalid_device_identifier_returns_422(self):
        for device_id in ["UPPER", "bad_id", "a" * 65]:
            with self.subTest(device_id=device_id):
                self.assertEqual(self.get_latest(device_id).status_code, 422)


if __name__ == "__main__":
    unittest.main()
