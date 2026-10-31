"""固定電表快照接口已退場；不能留下查不存在資料表的 500。"""
import unittest
from fastapi.testclient import TestClient
from api.main import create_app


class RetiredSnapshotApiTests(unittest.TestCase):
    def test_both_legacy_snapshot_routes_return_explicit_410(self):
        with TestClient(create_app()) as client:
            for url in ["/telemetry", "/devices/meter-001/telemetry/latest"]:
                with self.subTest(url=url):
                    response = client.get(url)
                    self.assertEqual(response.status_code,410)
                    self.assertIn("/points/{point_id}/readings",response.json()["detail"])

    def test_openapi_marks_snapshot_routes_deprecated(self):
        client = TestClient(create_app())
        schema = client.get("/openapi.json").json()
        for path in ["/telemetry","/devices/{device_id}/telemetry/latest"]:
            self.assertTrue(schema["paths"][path]["get"]["deprecated"])
