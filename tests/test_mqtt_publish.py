"""S2-02B：發布成功須有 Broker 確認，失敗不能冒充成功。"""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import paho.mqtt.client as mqtt

from gateway.mqtt_publish import PublishError, publish_telemetry


class MqttPublishTests(unittest.TestCase):
    def setUp(self):
        self.message = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/mqtt/telemetry.example.json")
            .read_text(encoding="utf-8")
        )
        self.client = Mock()
        self.client.connect.return_value = mqtt.MQTT_ERR_SUCCESS
        self.client.loop_start.return_value = mqtt.MQTT_ERR_SUCCESS
        self.client.loop_start.side_effect = lambda: self.client.on_connect(
            self.client, None, None, SimpleNamespace(is_failure=False), None
        ) or mqtt.MQTT_ERR_SUCCESS
        self.info = self.client.publish.return_value
        self.info.rc = mqtt.MQTT_ERR_SUCCESS
        self.info.is_published.return_value = True

    def publish(self):
        return publish_telemetry(self.message, client=self.client, timeout=0.01)

    def assert_failure(self, code):
        with self.assertRaises(PublishError) as caught:
            self.publish()
        self.assertEqual(caught.exception.code, code)
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()

    def test_publish_uses_contract_topic_json_qos1_and_no_retain(self):
        self.publish()
        args, kwargs = self.client.publish.call_args
        self.assertEqual(args[0], "okgo/demo/v1/devices/meter-001/telemetry")
        self.assertEqual(json.loads(kwargs["payload"]), self.message)
        self.assertEqual(kwargs["qos"], 1)
        self.assertIs(kwargs["retain"], False)
        self.info.wait_for_publish.assert_called_once_with(timeout=0.01)
        self.info.is_published.assert_called_once()
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()

    def test_tcp_connection_failure_does_not_publish(self):
        self.client.connect.side_effect = ConnectionRefusedError("refused")
        self.assert_failure("broker_connection_failed")
        self.client.publish.assert_not_called()

    def test_connack_timeout_does_not_publish(self):
        self.client.loop_start.side_effect = None
        self.assert_failure("broker_connack_timeout")
        self.client.publish.assert_not_called()

    def test_rejected_connection_does_not_publish(self):
        self.client.loop_start.side_effect = lambda: self.client.on_connect(
            self.client, None, None, SimpleNamespace(is_failure=True), None
        ) or mqtt.MQTT_ERR_SUCCESS
        self.assert_failure("broker_connection_rejected")
        self.client.publish.assert_not_called()

    def test_missing_puback_is_unconfirmed(self):
        self.info.is_published.return_value = False
        self.assert_failure("publish_unconfirmed")

    def test_publish_error_result_is_not_success(self):
        self.info.rc = mqtt.MQTT_ERR_NO_CONN
        self.assert_failure("publish_unconfirmed")

    def test_wait_error_is_unconfirmed(self):
        self.info.wait_for_publish.side_effect = RuntimeError("disconnected")
        self.assert_failure("publish_unconfirmed")


if __name__ == "__main__":
    unittest.main()
