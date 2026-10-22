"""驗證單次 CLI 的成功邊界與設備／Broker 錯誤分流。"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from gateway.mqtt_publish import PublishError
from gateway.publish_once import main


class PublishOnceTests(unittest.TestCase):
    def run_cli(self, device_ok=True, publish_error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("gateway.publish_once.ModbusTcpClient") as factory, \
             patch("gateway.publish_once.publish_telemetry") as publish:
            client = factory.return_value
            client.connect.return_value = device_ok
            response = client.read_holding_registers.return_value
            response.isError.return_value = False
            response.registers = [2300, 1000, 2300, 1, 4464]
            publish.side_effect = publish_error
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([])
            return code, stdout.getvalue(), stderr.getvalue(), publish

    def test_acknowledged_publish_logs_the_same_message_id(self):
        code, stdout, stderr, publish = self.run_cli()
        self.assertEqual(code, 0)
        message = publish.call_args.args[0]
        acquired = json.loads(stderr)
        result = json.loads(stdout)
        self.assertEqual(result["event"], "publish_acknowledged")
        self.assertEqual(result["message_id"], message["message_id"])
        self.assertEqual(acquired["message_id"], message["message_id"])
        self.assertEqual(result["acquired_at"], message["acquired_at"])
        self.assertEqual(message["device_id"], "meter-001")

    def test_device_failure_never_calls_publisher(self):
        code, stdout, stderr, publish = self.run_cli(device_ok=False)
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(json.loads(stderr)["code"], "connection_failed")
        publish.assert_not_called()

    def test_unconfirmed_publish_has_no_success_output(self):
        code, stdout, stderr, publish = self.run_cli(
            publish_error=PublishError("publish_unconfirmed", "PUBACK timeout")
        )
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        failure = json.loads(stderr.splitlines()[-1])
        self.assertEqual(failure["code"], "publish_unconfirmed")
        self.assertEqual(failure["message_id"], publish.call_args.args[0]["message_id"])


if __name__ == "__main__":
    unittest.main()
