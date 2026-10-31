"""真實 ModbusSerialClient、PySerial 與 RTU CRC；socket 測試傳輸不代表實體 RS-485 已驗證。"""
from contextlib import redirect_stderr
import io
import socket
from threading import Thread
import unittest

from pymodbus.framer import FramerRTU

from gateway.config import DeviceSettings, RtuChannel
from gateway.device.reader import create_client, read_device


class RtuTransportTests(unittest.TestCase):
    def test_two_units_share_rtu_channel_and_decode_real_crc_responses(self):
        requests, errors = [], []
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(5)
            port = listener.getsockname()[1]
            def serve():
                try:
                    for _ in range(2):
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(3)
                            request = b""
                            while len(request) < 8:
                                chunk = connection.recv(8 - len(request))
                                if not chunk:
                                    raise RuntimeError("RTU request truncated")
                                request += chunk
                            requests.append(request)
                            payload = bytes([request[0], 4, 2, 0xff, 0x85])
                            connection.sendall(payload + FramerRTU.compute_CRC(payload).to_bytes(2, "big"))
                except Exception as exc:
                    errors.append(exc)
            thread = Thread(target=serve)
            thread.start()
            try:
                channel = RtuChannel(channel_id="rtu", protocol="modbus_rtu",
                                     serial_port=f"socket://127.0.0.1:{port}", parity="N", timeout_seconds=1)
                client = create_client(channel)
                for unit in [1, 2]:
                    device = DeviceSettings.model_validate({"device_id":f"temp-{unit}",
                        "channel_id":"rtu", "unit_id":unit,
                        "points":[{"code":"temperature", "register_type":"input", "address":100,
                                   "data_type":"int16", "scale":"0.1"}]})
                    with redirect_stderr(io.StringIO()):
                        readings = read_device(client, device)
                    self.assertEqual([r["value"] for r in readings], ["-12.3"])
            finally:
                thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
        self.assertEqual([request[:6] for request in requests],
                         [bytes([1, 4, 0, 100, 0, 1]), bytes([2, 4, 0, 100, 0, 1])])
        self.assertTrue(all(FramerRTU.check_CRC(r[:-2], int.from_bytes(r[-2:], "big")) for r in requests))
