"""多點位讀取與通道選擇；失敗不能補零，其他點位可繼續採集。"""
from contextlib import redirect_stderr
import io
import unittest
from unittest.mock import Mock, patch

from gateway.config import DeviceSettings, RtuChannel, TcpChannel
from gateway.device.reader import create_client, read_device


def response(words):
    value = Mock()
    value.isError.return_value = False
    value.registers = words
    return value


def device_settings():
    return DeviceSettings.model_validate({"device_id":"sensor-001", "channel_id":"bus", "unit_id":2,
        "points":[{"code":"temperature", "register_type":"input", "address":100,
                   "data_type":"int16", "scale":"0.1"},
                  {"code":"energy", "address":120, "data_type":"uint32"}]})


class DeviceReaderTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.connect.return_value = True
        client.read_input_registers.return_value = response([65413])
        client.read_holding_registers.return_value = response([1, 4464])
        return client

    def test_noncontiguous_points_use_correct_function_address_count_and_unit(self):
        client = self.client()
        readings = read_device(client, device_settings())
        client.read_input_registers.assert_called_once_with(100, count=1, device_id=2)
        client.read_holding_registers.assert_called_once_with(120, count=2, device_id=2)
        self.assertEqual([r["value"] for r in readings], ["-12.3", "70000"])
        self.assertTrue(all(r["acquired_at"].endswith("+00:00") for r in readings))
        client.close.assert_called_once()

    def test_disconnected_device_has_no_fake_readings_and_closes(self):
        client = self.client()
        client.connect.return_value = False
        with redirect_stderr(io.StringIO()):
            self.assertEqual(read_device(client, device_settings()), [])
        client.read_holding_registers.assert_not_called()
        client.close.assert_called_once()

    def test_point_failure_does_not_discard_other_point(self):
        for failure in [OSError("offline"), ValueError("invalid response")]:
            client = self.client()
            client.read_input_registers.side_effect = failure
            with redirect_stderr(io.StringIO()) as errors:
                readings = read_device(client, device_settings())
            self.assertEqual([r["code"] for r in readings], ["energy"])
            self.assertIn('"point_code": "temperature"', errors.getvalue())

    def test_modbus_error_and_short_response_are_not_values(self):
        for result in [response([]), Mock(isError=Mock(return_value=True))]:
            client = self.client()
            client.read_input_registers.return_value = result
            with redirect_stderr(io.StringIO()):
                self.assertEqual(len(read_device(client, device_settings())), 1)

    def test_programming_error_propagates_and_closes(self):
        client = self.client()
        client.read_input_registers.side_effect = RuntimeError("bug")
        with self.assertRaisesRegex(RuntimeError, "bug"):
            read_device(client, device_settings())
        client.close.assert_called_once()

    def test_tcp_client_uses_channel_settings(self):
        channel = TcpChannel(channel_id="tcp", protocol="modbus_tcp", host="localhost", port=1503)
        with patch("gateway.device.reader.ModbusTcpClient") as factory:
            create_client(channel)
        factory.assert_called_once_with("localhost", port=1503, timeout=1.0, retries=0)

    def test_rtu_client_uses_real_serial_api_with_configured_parameters(self):
        channel = RtuChannel(channel_id="rtu", protocol="modbus_rtu", serial_port="COM9",
                             baudrate=19200, bytesize=8, parity="O", stopbits=2, timeout_seconds=0.2)
        with patch("gateway.device.reader.ModbusSerialClient") as factory:
            create_client(channel)
        factory.assert_called_once_with("COM9", baudrate=19200, bytesize=8,
                                        parity="O", stopbits=2, timeout=0.2, retries=0)

    def test_missing_serial_port_is_reported_without_crashing_reader(self):
        client = create_client(RtuChannel(channel_id="rtu", protocol="modbus_rtu",
                                         serial_port="unavailable-test-serial-port"))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(read_device(client, device_settings()), [])
