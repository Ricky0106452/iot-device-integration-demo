"""S2-03A：接收模型必須執行 v1 訊息規則。"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from gateway.telemetry import build_telemetry
from receiver.models import Telemetry

ROOT = Path(__file__).resolve().parents[1]


class TelemetryModelTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(
            (ROOT / "docs/mqtt/telemetry.example.json").read_text(encoding="utf-8")
        )

    def parse(self, message):
        return Telemetry.model_validate_json(json.dumps(message))

    def test_valid_json_becomes_model_without_changing_values(self):
        model = self.parse(self.example)
        self.assertEqual(model.device_id, "meter-001")
        self.assertEqual(model.measurement.voltage_v, 230.0)
        self.assertEqual(model.model_dump(mode="json"), self.example)

    def test_accepts_actual_gateway_message(self):
        snapshot = {"status": "ok", "device_id": 1,
                    "acquired_at": "2026-10-22T09:30:44.666262+00:00",
                    "raw_registers": self.example["raw_registers"],
                    "measurement": self.example["measurement"]}
        message = build_telemetry(snapshot, device_id="meter-001", gateway_id="gateway-001")
        self.assertEqual(self.parse(message).model_dump(mode="json"), message)

    def test_every_contract_field_is_required(self):
        for field in self.example:
            message = deepcopy(self.example)
            del message[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.parse(message)
        for field in self.example["measurement"]:
            message = deepcopy(self.example)
            del message["measurement"][field]
            with self.subTest(measurement=field), self.assertRaises(ValidationError):
                self.parse(message)

    def test_rejects_wrong_types_without_coercion(self):
        changes = [
            (("schema_version",), True), (("schema_version",), "1"),
            (("device_id",), 1), (("measurement", "voltage_v"), "230.0"),
            (("measurement", "current_a"), True), (("measurement", "power_w"), 2300.5),
            (("measurement", "energy_wh"), None), (("raw_registers",), [True, 0, 0, 0, 0]),
        ]
        for path, value in changes:
            message = deepcopy(self.example)
            target = message
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path, value=value), self.assertRaises(ValidationError):
                self.parse(message)

    def test_rejects_extra_fields_at_both_levels(self):
        for nested in [False, True]:
            message = deepcopy(self.example)
            target = message["measurement"] if nested else message
            target["unexpected"] = 1
            with self.subTest(nested=nested), self.assertRaises(ValidationError):
                self.parse(message)

    def test_rejects_invalid_version_identifiers_and_time(self):
        changes = [
            ("schema_version", 2), ("message_id", "not-a-uuid"),
            ("message_id", self.example["message_id"].upper()),
            ("device_id", "meter/001"), ("device_id", "meter-001\n"),
            ("gateway_id", "a" * 65),
            ("acquired_at", "2026-02-30T01:00:00Z"),
            ("acquired_at", "2026-10-22T01:00:00"),
            ("acquired_at", "2026-10-22T09:00:00+08:00"),
        ]
        for field, value in changes:
            message = dict(self.example, **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                self.parse(message)

    def test_accepts_zero_high_values_and_encoding_maximum(self):
        cases = [
            ([0, 0, 0, 0, 0], dict(voltage_v=0, current_a=0, power_w=0, energy_wh=0)),
            ([4300, 4000, 6000, 1, 4464], dict(voltage_v=430, current_a=40, power_w=6000, energy_wh=70000)),
            ([65535] * 5, dict(voltage_v=6553.5, current_a=655.35, power_w=65535, energy_wh=4294967295)),
        ]
        for raw, measurement in cases:
            message = dict(self.example, raw_registers=raw, measurement=measurement)
            with self.subTest(raw=raw):
                self.assertEqual(self.parse(message).model_dump(mode="json"), message)

    def test_rejects_invalid_raw_words_lengths_and_encoding_bounds(self):
        for raw in [[0] * 4, [0] * 6, [-1, 0, 0, 0, 0], [65536, 0, 0, 0, 0]]:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                self.parse(dict(self.example, raw_registers=raw))
        for field, value in [("voltage_v", -1), ("voltage_v", 6553.6),
                             ("current_a", 655.36), ("power_w", 65536),
                             ("energy_wh", 4294967296), ("voltage_v", float("nan")),
                             ("current_a", float("inf"))]:
            message = deepcopy(self.example)
            message["measurement"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                self.parse(message)


if __name__ == "__main__":
    unittest.main()
