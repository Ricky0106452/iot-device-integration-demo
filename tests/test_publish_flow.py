"""S2-01：設備採集失敗時，不得呼叫發布函式。"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import socket
import unittest
from unittest.mock import Mock

from pymodbus.client import ModbusTcpClient

from gateway.publish_flow import acquire_and_publish


class PublishFlowTests(unittest.TestCase):
    def assert_connection_failure(self, client):
        publish = Mock()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = acquire_and_publish(client, publish, device_id=1)
        self.assertNotEqual(exit_code, 0)
        publish.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        error = json.loads(stderr.getvalue().strip().splitlines()[-1])
        self.assertEqual(error["code"], "connection_failed")
        self.assertIn("attempt_finished_at", error)
        self.assertNotIn("measurement", error)
        self.assertNotIn("message_id", error)

    def test_connection_failure_does_not_publish(self):
        client = Mock()
        client.connect.return_value = False
        self.assert_connection_failure(client)
        client.read_holding_registers.assert_not_called()
        client.close.assert_called_once_with()

    def test_successful_acquisition_reaches_publisher(self):
        # 成功情境作為對照，避免「永遠不發布」的錯誤實作也能通過測試。
        client = Mock()
        client.connect.return_value = True
        response = client.read_holding_registers.return_value
        response.isError.return_value = False
        response.registers = [2300, 1000, 2300, 1, 4464]
        publish = Mock()

        self.assertEqual(acquire_and_publish(client, publish, device_id=1), 0)
        publish.assert_called_once()
        snapshot = publish.call_args.args[0]
        self.assertEqual(snapshot["raw_registers"], response.registers)
        self.assertEqual(snapshot["measurement"]["energy_wh"], 70000)
        client.close.assert_called_once_with()

    def test_real_unavailable_endpoint_does_not_publish(self):
        # 保留一個未監聽的本機端點，重現連線失敗，無須停止使用者的模擬器。
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            client = ModbusTcpClient(
                "127.0.0.1", port=endpoint.getsockname()[1], timeout=0.2, retries=0
            )
            self.assert_connection_failure(client)


if __name__ == "__main__":
    unittest.main()
