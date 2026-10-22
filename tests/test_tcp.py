"""Exercise separate simulator/client processes over a local TCP socket."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

from pymodbus.client import ModbusTcpClient

ROOT = Path(__file__).resolve().parents[1]


class TcpReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.server = subprocess.Popen(
            [sys.executable, "-u", "-m", "simulator.server", "--port", str(cls.port)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if cls.server.poll() is not None:
                    raise RuntimeError(cls.server.stdout.read())
                with socket.socket() as probe:
                    probe.settimeout(0.1)
                    if probe.connect_ex(("127.0.0.1", cls.port)) == 0:
                        return
                time.sleep(0.05)
            raise RuntimeError("Simulator did not start within 5 seconds")
        except Exception:
            cls.stop_server()
            raise

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait()
        cls.server.stdout.close()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()

    def test_read_once_from_separate_process(self):
        result = subprocess.run(
            [sys.executable, "-m", "gateway.read_once", "--port", str(self.port)],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["raw_registers"], [2300, 1000, 2300, 1, 4464])
        self.assertEqual(payload["measurement"], {
            "voltage_v": 230.0, "current_a": 10.0, "power_w": 2300, "energy_wh": 70000,
        })
        self.assertTrue(payload["acquired_at"].endswith("+00:00"))

    def test_undefined_address_and_writes_are_rejected(self):
        client = ModbusTcpClient("127.0.0.1", port=self.port, timeout=1, retries=0)
        try:
            self.assertTrue(client.connect())
            self.assertTrue(client.read_holding_registers(5, count=1, device_id=1).isError())
            self.assertTrue(client.write_register(0, 0, device_id=1).isError())
            self.assertEqual(client.read_holding_registers(0, count=1, device_id=1).registers,
                             [2300])
        finally:
            client.close()

    def test_connection_failure_has_no_measurement(self):
        # Reserve a non-listening endpoint: no other device can claim it during this check.
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            port = endpoint.getsockname()[1]
            result = subprocess.run(
                [sys.executable, "-m", "gateway.read_once", "--port", str(port),
                 "--timeout", "0.2"],
                cwd=ROOT, capture_output=True, text=True, timeout=5,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        payload = json.loads(result.stderr.strip().splitlines()[-1])
        self.assertEqual(payload["code"], "connection_failed")
        self.assertNotIn("measurement", payload)
