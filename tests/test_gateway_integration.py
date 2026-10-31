"""獨立 Modbus Server → 設定檔 Gateway 程序 → 真實 SQLite → 獨立 MQTT Broker。"""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
from queue import Queue
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from uuid import uuid4

import paho.mqtt.client as mqtt

from gateway.buffering.outbox import Outbox
from gateway.buffering.sender import OutboxSender
from gateway.messaging.publisher import PublishError, publish_telemetry
from gateway_test_support import settings_payload

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("IOT_RECOVERY_BROKER_PORT"), "未設定獨立測試 MQTT Broker")
class GatewayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.broker_port = int(os.environ["IOT_RECOVERY_BROKER_PORT"])
        if self.broker_port == 1883:
            raise RuntimeError("不可使用展示 Broker")

    def test_configured_multi_device_process_publishes_noncontiguous_points(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                modbus_port = probe.getsockname()[1]
            with (directory / "server.log").open("w", encoding="utf-8") as server_log:
                server = subprocess.Popen([sys.executable, "tests/gateway_modbus_server.py", str(modbus_port)],
                    cwd=ROOT, stdout=server_log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        with socket.socket() as probe:
                            if probe.connect_ex(("127.0.0.1", modbus_port)) == 0:
                                break
                        if server.poll() is not None or time.monotonic() >= deadline:
                            self.fail("Modbus test server failed: " + (directory / "server.log").read_text(encoding="utf-8"))
                        time.sleep(0.05)
                    data = settings_payload()
                    prefix = "test/gateway-" + uuid4().hex + "/v2"
                    data["mqtt"].update(port=self.broker_port, topic_prefix=prefix)
                    data["buffer"]["path"] = "test-outbox.sqlite3"
                    data["channels"][0]["port"] = modbus_port
                    data["devices"] = [
                        {"device_id":"meter-001", "channel_id":"meter-tcp", "unit_id":1,
                         "interval_seconds":1, "points":[
                             {"code":"voltage", "address":0, "data_type":"uint16", "scale":"0.1"},
                             {"code":"current", "address":10, "data_type":"uint16", "scale":"0.01"}]},
                        {"device_id":"temperature-001", "channel_id":"meter-tcp", "unit_id":2,
                         "interval_seconds":1, "points":[
                             {"code":"temperature", "register_type":"input", "address":100,
                              "data_type":"int16", "scale":"0.1"},
                             {"code":"energy", "address":120, "data_type":"uint32", "word_order":"little"}]},
                    ]
                    config = directory / "appsettings.json"
                    config.write_text(json.dumps(data), encoding="utf-8")
                    received, subscribed = Queue(), Event()
                    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                    subscriber.on_connect = lambda client, *_: client.subscribe(prefix + "/devices/+/telemetry", qos=1)
                    subscriber.on_subscribe = lambda *_: subscribed.set()
                    subscriber.on_message = lambda _, __, message: received.put((message.topic, json.loads(message.payload)))
                    gateway = None
                    try:
                        subscriber.connect("127.0.0.1", self.broker_port)
                        subscriber.loop_start()
                        self.assertTrue(subscribed.wait(5))
                        with (directory / "gateway.log").open("w", encoding="utf-8") as gateway_log:
                            gateway = subprocess.Popen([sys.executable, "-u", "-c",
                                "import sys; from gateway.main import main; raise SystemExit(main(sys.argv[1]))", str(config)],
                                cwd=ROOT, stdout=gateway_log, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                            messages = {}
                            for _ in range(4):
                                topic, message = received.get(timeout=8)
                                messages[message["device_id"]] = (topic, message)
                                if len(messages) == 2:
                                    break
                            self.assertEqual(set(messages), {"meter-001", "temperature-001"})
                            for device_id, (topic, message) in messages.items():
                                self.assertEqual(topic, prefix + f"/devices/{device_id}/telemetry")
                                self.assertEqual(message["schema_version"], 2)
                            meter = {r["code"]:r["value"] for r in messages["meter-001"][1]["readings"]}
                            temperature = {r["code"]:r["value"] for r in messages["temperature-001"][1]["readings"]}
                            self.assertEqual(meter, {"voltage":"230.0", "current":"10.00"})
                            self.assertEqual(temperature, {"temperature":"-12.3", "energy":"655"})
                            self.assertTrue((directory / "test-outbox.sqlite3").exists())
                    finally:
                        if gateway is not None:
                            gateway.terminate()
                            gateway.wait(timeout=5)
                        subscriber.disconnect()
                        subscriber.loop_stop()
                finally:
                    server.terminate()
                    server.wait(timeout=5)

    def test_offline_publish_keeps_message_and_reopen_replays_original_to_real_broker(self):
        message = {"schema_version":2, "message_id":str(uuid4()), "gateway_id":"gateway-test",
                   "device_id":"sensor-test", "acquired_at":"2026-10-31T00:00:00+00:00",
                   "readings":[{"code":"temperature", "value":"26.5", "unit":"degC",
                                "acquired_at":"2026-10-31T00:00:00+00:00"}]}
        topic = "test/replay-" + uuid4().hex
        received, ready = Queue(), Event()
        subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        subscriber.on_connect = lambda client, *_: client.subscribe(topic, qos=1)
        subscriber.on_subscribe = lambda *_: ready.set()
        subscriber.on_message = lambda _, __, item: received.put(json.loads(item.payload))
        try:
            subscriber.connect("127.0.0.1", self.broker_port)
            subscriber.loop_start()
            self.assertTrue(ready.wait(5))
            with TemporaryDirectory() as directory:
                path = Path(directory) / "outbox.sqlite3"
                with socket.socket() as endpoint, Outbox(path, max_pending=10) as box:
                    endpoint.bind(("127.0.0.1", 0))
                    unavailable_port = endpoint.getsockname()[1]
                    box.enqueue(topic, message)
                    def offline(item, **kwargs):
                        publish_telemetry(item, port=unavailable_port, timeout=0.1, **kwargs)
                    with redirect_stderr(io.StringIO()):
                        self.assertFalse(OutboxSender(box, offline).deliver_next())
                    self.assertEqual(box.oldest().message, message)
                with Outbox(path, max_pending=10) as box:
                    def online(item, **kwargs):
                        publish_telemetry(item, port=self.broker_port, **kwargs)
                    self.assertTrue(OutboxSender(box, online).deliver_next())
                    self.assertEqual(box.count(), 0)
                    self.assertEqual(received.get(timeout=5), message)
        finally:
            subscriber.disconnect()
            subscriber.loop_stop()
