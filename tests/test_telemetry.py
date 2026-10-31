"""v2 通用點位訊息的時間、精度與複製邊界。"""
from copy import deepcopy
import unittest
from uuid import UUID

from gateway.messaging.telemetry import build_telemetry, telemetry_topic


class BuildTelemetryTests(unittest.TestCase):
    def readings(self):
        return [{"code":"temperature", "unit":"degC", "value":"-12.3",
                 "acquired_at":"2026-10-31T00:00:00+00:00"}]

    def build(self, readings=None):
        return build_telemetry(self.readings() if readings is None else readings,
                               device_id="sensor-001", gateway_id="gateway-001")

    def test_generic_message_preserves_per_point_time_and_decimal_string(self):
        readings = self.readings()
        message = self.build(readings)
        self.assertEqual(message["schema_version"], 2)
        self.assertEqual(message["readings"], readings)
        self.assertNotIn("measurement", message)
        self.assertEqual(UUID(message["message_id"]).version, 4)

    def test_new_acquisition_gets_new_message_id(self):
        self.assertNotEqual(self.build()["message_id"], self.build()["message_id"])

    def test_later_mutation_does_not_change_saved_message(self):
        readings = self.readings()
        message = self.build(readings)
        before = deepcopy(message)
        readings[0]["value"] = "999"
        self.assertEqual(message, before)

    def test_no_successful_points_does_not_create_message(self):
        with self.assertRaises(ValueError):
            self.build([])

    def test_topic_uses_configured_prefix_and_device_id(self):
        self.assertEqual(telemetry_topic("plant/v2", "sensor-001"),
                         "plant/v2/devices/sensor-001/telemetry")
