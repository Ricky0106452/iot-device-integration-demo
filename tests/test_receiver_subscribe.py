"""S2-03B：合法訊息可處理，非法訊息不能中止接收。"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import paho.mqtt.client as mqtt

from receiver.subscribe import handle_message, run_receiver
from storage.device_setup import DeviceConfigurationError

TOPIC = "okgo/demo/v1/devices/meter-001/telemetry"


class ReceiverSubscribeTests(unittest.TestCase):
    def setUp(self):
        self.message = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/mqtt/telemetry.example.json")
            .read_text(encoding="utf-8")
        )
        self.store = Mock(return_value="stored")
        self.client = Mock()
        self.client.ack.return_value = mqtt.MQTT_ERR_SUCCESS
        self.client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
        self.client.loop_start.return_value = mqtt.MQTT_ERR_SUCCESS
        self.client.loop_start.side_effect = lambda: self.client.on_connect(
            self.client, None, None, SimpleNamespace(is_failure=False), None
        ) or mqtt.MQTT_ERR_SUCCESS
        self.client.subscribe.return_value = (mqtt.MQTT_ERR_SUCCESS, 1)

    def test_valid_payload_is_stored_before_success_log(self):
        output = io.StringIO()
        before = datetime.now().astimezone()
        def stored_after_commit(*args, **kwargs):
            self.assertEqual(output.getvalue(), "")
            return "stored"
        self.store.side_effect = stored_after_commit
        with redirect_stdout(output):
            handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
        after = datetime.now().astimezone()
        event = json.loads(output.getvalue())
        self.assertEqual(event["event"], "telemetry_stored")
        self.store.assert_called_once()
        model = self.store.call_args.args[0]
        self.assertEqual(model.measurement.power_w, 2300)
        self.assertEqual(self.store.call_args.kwargs["received_at"].isoformat(), event["received_at"])
        self.assertNotIn("measurement", event)
        self.assertIn("stored_at", event)
        for key in ["message_id", "device_id", "gateway_id", "acquired_at"]:
            self.assertEqual(event[key], self.message[key])
        self.assertEqual(event["topic"], TOPIC)
        self.assertLessEqual(before, datetime.fromisoformat(event["received_at"]))
        self.assertLessEqual(datetime.fromisoformat(event["received_at"]), after)

    def test_missing_field_then_valid_message_continues(self):
        invalid = dict(self.message)
        del invalid["message_id"]
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            handle_message(TOPIC, json.dumps(invalid).encode(), store=self.store)
            handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
        self.store.assert_called_once()
        rejected = json.loads(errors.getvalue())
        self.assertEqual(rejected["event"], "telemetry_rejected")
        self.assertEqual(rejected["code"], "invalid_payload")
        self.assertEqual(rejected["topic"], TOPIC)
        self.assertEqual(json.loads(output.getvalue())["message_id"], self.message["message_id"])

    def test_invalid_json_and_utf8_are_rejected_without_payload_dump(self):
        for raw in [b'{bad secret-data', b'\xff']:
            with self.subTest(raw=raw):
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    handle_message(TOPIC, raw, store=self.store)
                self.store.assert_not_called()
                self.assertEqual(output.getvalue(), "")
                rejected = json.loads(errors.getvalue())
                self.assertEqual(rejected["code"], "invalid_json")
                self.assertNotIn("secret-data", errors.getvalue())


    def test_invalid_precision_is_rejected_before_storage(self):
        for field, value in [("voltage_v", 230.04), ("current_a", 10.001)]:
            with self.subTest(field=field):
                self.message["measurement"][field] = value
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
                self.store.assert_not_called()
                self.assertEqual(output.getvalue(), "")
                event = json.loads(errors.getvalue())
                self.assertEqual(event["event"], "telemetry_rejected")
                self.assertEqual(event["field"], ["measurement", field])
                self.message["measurement"][field] = 230.0 if field == "voltage_v" else 10.0

    def test_duplicate_and_conflict_log_the_storage_result(self):
        for result in ["duplicate", "conflict"]:
            with self.subTest(result=result):
                self.store.return_value = result
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
                event = json.loads(errors.getvalue() if result == "conflict" else output.getvalue())
                self.assertEqual(event["event"], f"telemetry_{result}")
                self.assertEqual(event["message_id"], self.message["message_id"])
                self.assertNotIn("stored_at", event)

    def test_configuration_rejection_does_not_stop_next_valid_message(self):
        self.store.side_effect = [DeviceConfigurationError("點位尚未設定"), "stored"]
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
            handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
        self.assertEqual(json.loads(errors.getvalue())["code"], "device_configuration_error")
        self.assertEqual(json.loads(output.getvalue())["event"], "telemetry_stored")
        self.assertEqual(self.store.call_count, 2)

    def test_storage_error_does_not_log_success_or_disappear(self):
        self.store.side_effect = RuntimeError("寫入失敗")
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "寫入失敗"):
            handle_message(TOPIC, json.dumps(self.message).encode(), store=self.store)
        self.assertEqual(output.getvalue(), "")

    def test_mqtt_callback_passes_validated_message_to_storage(self):
        def subscribed_and_received(*args, **kwargs):
            self.client.on_subscribe(self.client, None, 1, [SimpleNamespace(value=1)], None)
            self.client.on_message(self.client, None, SimpleNamespace(
                topic=TOPIC, payload=json.dumps(self.message).encode(), mid=7, qos=1))
            self.client.on_disconnect(self.client, None, None, SimpleNamespace(), None)
            return mqtt.MQTT_ERR_SUCCESS, 1
        self.client.subscribe.side_effect = subscribed_and_received
        code, output, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.store.assert_called_once()
        events = [json.loads(line)["event"] for line in output.splitlines()]
        self.assertIn("telemetry_stored", events)

    def capture_run(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = run_receiver(self.client, store=self.store, timeout=0.01)
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()
        return code, output.getvalue(), errors.getvalue()

    def test_broker_connection_failure_does_not_subscribe(self):
        self.client.connect.side_effect = ConnectionRefusedError("refused")
        code, output, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertEqual(json.loads(errors)["code"], "broker_connection_failed")
        self.client.subscribe.assert_not_called()

    def test_connack_rejection_does_not_subscribe(self):
        self.client.loop_start.side_effect = lambda: self.client.on_connect(
            self.client, None, None, SimpleNamespace(is_failure=True), None
        ) or mqtt.MQTT_ERR_SUCCESS
        code, output, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertEqual(json.loads(errors)["code"], "broker_connection_rejected")
        self.client.subscribe.assert_not_called()

    def test_suback_must_grant_qos_one_before_ready(self):
        def rejected_subscribe(*args, **kwargs):
            self.client.on_subscribe(self.client, None, 1, [SimpleNamespace(value=0)], None)
            return mqtt.MQTT_ERR_SUCCESS, 1
        self.client.subscribe.side_effect = rejected_subscribe
        code, output, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertEqual(json.loads(errors)["code"], "subscription_rejected")

    def test_ready_then_disconnect_exits_instead_of_reconnecting(self):
        def subscribed_then_disconnected(*args, **kwargs):
            self.client.on_subscribe(self.client, None, 1, [SimpleNamespace(value=1)], None)
            self.client.on_disconnect(self.client, None, None, SimpleNamespace(), None)
            return mqtt.MQTT_ERR_SUCCESS, 1
        self.client.subscribe.side_effect = subscribed_then_disconnected
        code, output, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output)["event"], "receiver_ready")
        self.assertEqual(json.loads(errors)["code"], "broker_disconnected")
        self.client.subscribe.assert_called_once_with("okgo/demo/v1/devices/+/telemetry", qos=1)


class ReceiverAckTests(unittest.TestCase):
    setUp = ReceiverSubscribeTests.setUp
    capture_run = ReceiverSubscribeTests.capture_run
    def deliver(self, *, payload=None, result='stored', failure=None, ack_result=mqtt.MQTT_ERR_SUCCESS):
        self.store.return_value = result
        self.store.side_effect = failure
        self.client.ack.return_value = ack_result
        order = []
        if failure is None:
            self.store.side_effect = lambda *a, **kw: order.append('store_completed') or result
        self.client.ack.side_effect = lambda *a: order.append('ack') or ack_result
        def subscribed(*args, **kwargs):
            self.client.on_subscribe(self.client, None, 1, [SimpleNamespace(value=1)], None)
            self.client.on_message(self.client, None, SimpleNamespace(
                topic=TOPIC, payload=payload if payload is not None else json.dumps(self.message).encode(),
                mid=9, qos=1))
            self.client.on_disconnect(self.client, None, None, SimpleNamespace(), None)
            return mqtt.MQTT_ERR_SUCCESS, 1
        self.client.subscribe.side_effect = subscribed
        return order

    def test_ack_follows_store_or_duplicate_or_conflict_result(self):
        for result in ['stored', 'duplicate', 'conflict']:
            with self.subTest(result=result):
                self.setUp()
                order = self.deliver(result=result)
                self.capture_run()
                self.assertEqual(order, ['store_completed', 'ack'])
                self.client.ack.assert_called_once_with(9, 1)

    def test_invalid_message_is_acknowledged_after_rejection(self):
        order = self.deliver(payload=b'{}')
        _, _, errors = self.capture_run()
        self.assertIn('invalid_payload', errors)
        self.store.assert_not_called()
        self.assertEqual(order, ['ack'])

    def test_configuration_rejection_is_acknowledged(self):
        self.deliver(failure=DeviceConfigurationError('not configured'))
        _, _, errors = self.capture_run()
        self.assertIn('device_configuration_error', errors)
        self.client.ack.assert_called_once_with(9, 1)

    def test_database_exception_does_not_ack(self):
        self.deliver(failure=RuntimeError('DB unavailable'))
        with self.assertRaisesRegex(RuntimeError, 'DB unavailable'):
            self.capture_run()
        self.client.ack.assert_not_called()
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()

    def test_ack_failure_is_reported(self):
        self.deliver(ack_result=mqtt.MQTT_ERR_NO_CONN)
        code, _, errors = self.capture_run()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(errors)['code'], 'mqtt_ack_failed')

    def test_main_uses_persistent_identity_and_manual_ack(self):
        from unittest.mock import patch
        from receiver.subscribe import main
        with patch('receiver.subscribe.mqtt.Client') as factory, \
             patch('receiver.subscribe.create_db_engine') as engine, \
             patch('receiver.subscribe.run_receiver', return_value=0):
            self.assertEqual(main(['--client-id', 'rx-test-001']), 0)
        self.assertEqual(factory.call_args.kwargs['client_id'], 'rx-test-001')
        self.assertFalse(factory.call_args.kwargs['clean_session'])
        self.assertTrue(factory.call_args.kwargs['manual_ack'])
        engine.return_value.dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
