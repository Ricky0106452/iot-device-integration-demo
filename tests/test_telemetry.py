"""S2-02A：成功快照轉成 v1 量測訊息。"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from uuid import UUID

from gateway.telemetry import build_telemetry

ROOT = Path(__file__).resolve().parents[1]


class BuildTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(
            (ROOT / "docs/mqtt/telemetry.example.json").read_text(encoding="utf-8")
        )
        self.snapshot = {
            "status": "ok",
            "device_id": 1,  # 內部快照的數值 ID 是 Modbus Unit ID。
            "acquired_at": self.example["acquired_at"],
            "raw_registers": list(self.example["raw_registers"]),
            "measurement": dict(self.example["measurement"]),
        }

    def build(self, snapshot=None):
        return build_telemetry(
            self.snapshot if snapshot is None else snapshot,
            device_id="meter-001", gateway_id="gateway-001",
        )

    def test_builds_contract_fields_and_preserves_acquisition(self):
        for words, measurement in [
            (self.example["raw_registers"], self.example["measurement"]),
            ([4300, 4000, 6000, 1, 4464],
             {"voltage_v": 430.0, "current_a": 40.0, "power_w": 6000, "energy_wh": 70000}),
        ]:
            with self.subTest(words=words):
                snapshot = dict(self.snapshot, raw_registers=words, measurement=measurement)
                before = deepcopy(snapshot)
                result = self.build(snapshot)
                expected = dict(self.example, raw_registers=words, measurement=measurement)
                expected["message_id"] = result["message_id"]
                self.assertEqual(result, expected)
                self.assertEqual(snapshot, before)
                message_id = UUID(result["message_id"])
                self.assertEqual(message_id.version, 4)
                self.assertEqual(str(message_id), result["message_id"])

    def test_identical_readings_get_distinct_message_ids(self):
        first, second = self.build(), self.build()
        self.assertNotEqual(first["message_id"], second["message_id"])
        self.assertEqual(first["acquired_at"], second["acquired_at"])
        self.assertEqual(first["measurement"], second["measurement"])

    def test_later_source_changes_do_not_change_built_message(self):
        result = self.build()
        self.snapshot["raw_registers"][0] = 0
        self.snapshot["measurement"]["voltage_v"] = 0
        self.assertEqual(result["raw_registers"][0], 2300)
        self.assertEqual(result["measurement"]["voltage_v"], 230.0)

    def test_failed_attempt_is_not_a_telemetry_message(self):
        with self.assertRaises(ValueError):
            self.build({"status": "error", "code": "connection_failed"})

    def test_rejects_ids_that_cannot_be_used_in_the_topic_contract(self):
        for field in ["device_id", "gateway_id"]:
            for invalid in [1, "", "Meter-001", "meter/001", "meter+", "-meter", "a" * 65]:
                with self.subTest(field=field, invalid=invalid):
                    ids = {"device_id": "meter-001", "gateway_id": "gateway-001"}
                    ids[field] = invalid
                    with self.assertRaises(ValueError):
                        build_telemetry(self.snapshot, **ids)


if __name__ == "__main__":
    unittest.main()
