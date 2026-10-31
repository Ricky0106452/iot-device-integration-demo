"""v2 訊息、接收端獨立設定、來源映射與 ACK 邊界。"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from receiver.config import ReceiverSettings, load_settings
from receiver.point_handler import handle_point_message
from receiver.point_models import PointTelemetry
from receiver.subscribe import run_receiver
from receiver_test_support import point_message, receiver_payload


class ReceiverPointContractTests(unittest.TestCase):
    def test_accepts_current_gateway_builder_output_without_importing_gateway_config(self):
        from gateway.messaging.telemetry import build_telemetry
        readings = point_message()["readings"]
        message = build_telemetry(readings, device_id="sensor-002", gateway_id="gateway-001")
        model = PointTelemetry.model_validate_json(json.dumps(message))
        self.assertEqual(model.readings[0].code, "temp2")

    def test_preserves_supported_float64_extremes_without_truncating_decimal_value(self):
        import struct
        import sys
        from gateway.device.decoding import decode_point
        from gateway.device.spec import PointSpec
        point = PointSpec(code="temp2", address=0, data_type="float64")
        for value in [sys.float_info.max, 5e-324]:
            raw = struct.pack(">d", value)
            registers = [int.from_bytes(raw[index:index+2], "big") for index in range(0, 8, 2)]
            decoded = decode_point(registers, point)
            message = point_message()
            message["readings"][0]["value"] = format(decoded, "f")
            model = PointTelemetry.model_validate_json(json.dumps(message))
            self.assertEqual(model.readings[0].value, decoded)

    def test_rejects_invalid_values_times_duplicate_codes_and_unknown_fields(self):
        mutations = [lambda d: d.update(schema_version=1), lambda d: d.update(schema_version=2.0),
            lambda d: d.update(message_id="invalid"), lambda d: d.update(readings=[]),
            lambda d: d["readings"][0].update(value=26.5),
            lambda d: d["readings"][0].update(value="NaN"),
            lambda d: d["readings"][0].update(value="Infinity"),
            lambda d: d["readings"][0].update(acquired_at="2026-10-31T08:00:00"),
            lambda d: d["readings"].append(deepcopy(d["readings"][0])),
            lambda d: d["readings"][0].update(extra="unknown")]
        for index, mutate in enumerate(mutations):
            data = point_message()
            mutate(data)
            with self.subTest(case=index), self.assertRaises(ValidationError):
                PointTelemetry.model_validate_json(json.dumps(data))

    def test_equivalent_decimal_and_timestamp_representations_are_canonical(self):
        first = point_message()
        second = deepcopy(first)
        second["readings"][0].update(value="26.500", acquired_at="2026-10-31T16:00:00+08:00")
        self.assertEqual(PointTelemetry.model_validate(first).canonical_content(),
                         PointTelemetry.model_validate(second).canonical_content())

    def test_config_separates_source_and_platform_identity(self):
        settings = ReceiverSettings.model_validate(receiver_payload())
        binding = settings.bindings[0]
        self.assertEqual(binding.source_code, "temp2")
        self.assertEqual(binding.target_point_code, "temp1")
        self.assertNotEqual(binding.source_device_id, binding.target_device_id)
        self.assertEqual(settings.topics, ("factory/test/environment",))

    def test_config_rejects_ambiguous_bindings_and_missing_target(self):
        for mutate in [lambda d: d["bindings"].append(deepcopy(d["bindings"][0])),
                       lambda d: d["bindings"][0].update(target_point_code="unknown"),
                       lambda d: d["bindings"][0].update(topic="factory/+/environment"),
                       lambda d: d["bindings"].append(dict(d["bindings"][0], source_code="another"))]:
            data = receiver_payload()
            mutate(data)
            with self.assertRaises(ValidationError):
                ReceiverSettings.model_validate(data)

    def test_platform_names_accept_100_characters_and_reject_101(self):
        for point_name in (False, True):
            data = receiver_payload()
            target = data["platform_devices"][0]["points"][0] if point_name else data["platform_devices"][0]
            target["name"] = "溫" * 100
            ReceiverSettings.model_validate(data)
            target["name"] = "溫" * 101
            with self.assertRaises(ValidationError):
                ReceiverSettings.model_validate(data)

    def test_shipped_receiver_configs_validate(self):
        for path in ["receiver.appsettings.json", "config/receiver.docker.json", "config/receiver.mapping.example.json"]:
            with self.subTest(path=path):
                self.assertTrue(load_settings(path).bindings)

    def test_handle_uses_actual_topic_and_does_not_require_matching_platform_name(self):
        store = Mock(return_value="stored")
        with redirect_stdout(io.StringIO()) as output:
            handle_point_message("factory/room/environment", json.dumps(point_message()).encode(), store=store)
        self.assertEqual(store.call_args.kwargs["topic"], "factory/room/environment")
        self.assertEqual(store.call_args.args[0].readings[0].code, "temp2")
        self.assertEqual(json.loads(output.getvalue())["event"], "telemetry_stored")


class ReceiverPointAckTests(unittest.TestCase):
    def deliver(self, failure=None, result="stored", payload=None):
        client = Mock()
        client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
        client.ack.return_value = mqtt.MQTT_ERR_SUCCESS
        client.loop_start.side_effect = lambda: client.on_connect(
            client, None, SimpleNamespace(session_present=False), SimpleNamespace(is_failure=False), None) or 0
        order = []
        def store(*args, **kwargs):
            if failure:
                raise failure
            order.append("committed")
            return result
        client.ack.side_effect = lambda *a: order.append("ack") or 0
        def subscribe(*args, **kwargs):
            client.on_subscribe(client, None, 1, [SimpleNamespace(value=1), SimpleNamespace(value=1)], None)
            client.on_message(client, None, SimpleNamespace(topic="factory/test/environment",
                payload=payload if payload is not None else json.dumps(point_message()).encode(), mid=9, qos=1))
            client.on_disconnect(client, None, None, None, None)
            return 0, 1
        client.subscribe.side_effect = subscribe
        return client, store, order

    def test_v2_ack_after_store_and_subscribes_all_configured_topics(self):
        client, store, order = self.deliver()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            run_receiver(client, store=store, message_handler=handle_point_message,
                         topic_filters=("factory/test/environment", "factory/other/environment"))
        self.assertEqual(order, ["committed", "ack"])
        client.subscribe.assert_called_once_with([("factory/test/environment", 1), ("factory/other/environment", 1)])

    def test_v2_database_failure_does_not_ack(self):
        client, store, order = self.deliver(failure=RuntimeError("DB unavailable"))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaisesRegex(RuntimeError, "DB unavailable"):
            run_receiver(client, store=store, message_handler=handle_point_message,
                         topic_filters=("factory/test/environment", "factory/other/environment"))
        client.ack.assert_not_called()

    def test_v2_invalid_or_unmapped_message_is_logged_and_acknowledged(self):
        for payload, result in [(b"{}", "stored"), (None, "unmapped")]:
            client, store, order = self.deliver(payload=payload, result=result)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                run_receiver(client, store=store, message_handler=handle_point_message,
                             topic_filters=("factory/test/environment", "factory/other/environment"))
            client.ack.assert_called_once()
            self.assertNotIn("telemetry_stored", errors.getvalue())
