"""已移除的快照路由不出現在 OpenAPI，也不再註冊相容端點。"""
import unittest
from fastapi.testclient import TestClient
from api.main import create_app


class RemovedSnapshotApiTests(unittest.TestCase):
    def test_removed_snapshot_paths_return_standard_404(self):
        with TestClient(create_app()) as client:
            for url in ["/telemetry", "/devices/meter-001/telemetry/latest"]:
                with self.subTest(url=url):
                    response = client.get(url)
                    self.assertEqual(response.status_code,404)
                    self.assertEqual(response.json(),{"detail":"Not Found"})

    def test_openapi_only_contains_current_device_and_point_routes(self):
        client = TestClient(create_app())
        paths = client.get("/openapi.json").json()["paths"]
        self.assertEqual(set(paths),{"/devices","/devices/{device_id}/points","/points/{point_id}/readings"})
