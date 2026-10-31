"""v2 來源映射的真實 MQTT/DB 恢復測試，故障注入僅存在測試子程序。"""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from uuid import uuid4

import paho.mqtt.client as mqtt
from sqlalchemy import delete
from sqlmodel import Session, select

from gateway.messaging.publisher import publish_telemetry
from receiver.config import ReceiverSettings
from storage.database import create_db_engine
from storage.models import Device, MeasurementPoint, SourceBinding, ReceivedMessage, PointReading
from storage.source_mapping import configure_sources
from test_storage_models import upgrade_database
from receiver_test_support import point_message, receiver_payload

ROOT = Path(__file__).resolve().parents[1]
WORKER = r'''
import json, sys
from threading import Event
import paho.mqtt.client as mqtt
from receiver.config import load_settings
from receiver.point_handler import handle_point_message
from receiver.subscribe import run_receiver
from storage.database import create_db_engine
from storage.point_telemetry import store_point_telemetry
settings = load_settings(sys.argv[1])
mode = sys.argv[2]
engine = create_db_engine(settings.database_url)
def store(model, *, topic, received_at):
    if mode == "before":
        print(json.dumps({"event":"before_commit"}), flush=True)
        Event().wait()
    result = store_point_telemetry(engine, model, receiver_id=settings.receiver_id,
                                  topic=topic, received_at=received_at)
    if mode == "after":
        print(json.dumps({"event":"after_commit"}), flush=True)
        Event().wait()
    return result
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.receiver_id,
    clean_session=False, manual_ack=True, protocol=mqtt.MQTTv311, reconnect_on_failure=False)
try:
    raise SystemExit(run_receiver(client, store=store, message_handler=handle_point_message,
        topic_filters=settings.topics, port=settings.mqtt.port))
finally:
    engine.dispose()
'''


@unittest.skipUnless(os.environ.get("IOT_TEST_DATABASE_URL") and os.environ.get("IOT_RECOVERY_BROKER_PORT"),
                     "未設定獨立測試 DB/Broker")
class PointReceiverRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.port = int(os.environ["IOT_RECOVERY_BROKER_PORT"])
        if self.port == 1883:
            raise RuntimeError("不可使用展示 Broker")
        self.engine = create_db_engine(os.environ["IOT_TEST_DATABASE_URL"])
        upgrade_database(self.engine)
        self.directory = TemporaryDirectory()
        self.processes = []
        self.data = receiver_payload(os.environ["IOT_TEST_DATABASE_URL"], uuid4().hex[:12])
        self.data["mqtt"]["port"] = self.port
        self.settings = ReceiverSettings.model_validate(self.data)
        self.config = Path(self.directory.name) / "receiver.json"
        self.config.write_text(json.dumps(self.data),encoding="utf-8")
        self.addCleanup(self.cleanup)
        configure_sources(self.engine, self.settings)
        self.message = point_message()

    def cleanup(self):
        for process in self.processes:
            self.stop(process)
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=self.settings.receiver_id, clean_session=True)
        try:
            client.connect("127.0.0.1", self.port)
            client.loop(timeout=1)
            client.disconnect()
        finally:
            with Session(self.engine) as session:
                receipts = select(ReceivedMessage.receipt_id).where(ReceivedMessage.receiver_id == self.settings.receiver_id)
                session.execute(delete(PointReading).where(PointReading.receipt_id.in_(receipts)))
                session.execute(delete(ReceivedMessage).where(ReceivedMessage.receiver_id == self.settings.receiver_id))
                session.execute(delete(SourceBinding).where(SourceBinding.receiver_id == self.settings.receiver_id))
                ids = [device.device_id for device in self.settings.platform_devices]
                session.execute(delete(MeasurementPoint).where(MeasurementPoint.device_id.in_(ids)))
                session.execute(delete(Device).where(Device.device_id.in_(ids)))
                session.commit()
            self.engine.dispose()
            self.directory.cleanup()

    def start(self, mode="normal"):
        process = subprocess.Popen([sys.executable, "-u", "-c", WORKER, str(self.config), mode],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.processes.append(process)
        process.events = Queue()
        process.pending = []
        def read():
            for line in process.stdout:
                process.events.put(line)
            process.events.put(None)
        process.reader = Thread(target=read, daemon=True)
        process.reader.start()
        return process

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.reader.join(timeout=2)
        process.stdout.close()

    def wait_event(self, process, event):
        for index, value in enumerate(process.pending):
            if value.get("event") == event:
                return process.pending.pop(index)
        deadline = time.monotonic()+10
        lines = []
        while time.monotonic()<deadline:
            try:
                line = process.events.get(timeout=max(0.01, deadline-time.monotonic()))
            except Empty:
                break
            if line is None:
                break
            lines.append(line)
            try:
                value = json.loads(line)
                if value.get("event") == event:
                    return value
                process.pending.append(value)
            except ValueError:
                pass
        self.fail("Missing " + event + ": " + "".join(lines))

    def publish(self):
        publish_telemetry(self.message, topic=self.settings.topics[0], port=self.port)

    def assert_one_mapped_value(self):
        with Session(self.engine) as session:
            receipts = session.exec(select(ReceivedMessage).where(ReceivedMessage.receiver_id == self.settings.receiver_id)).all()
            self.assertEqual(len(receipts),1)
            values = session.exec(select(PointReading).where(PointReading.receipt_id == receipts[0].receipt_id)).all()
            self.assertEqual(len(values),1)
            point = session.get(MeasurementPoint, values[0].point_id)
            self.assertEqual(point.code,"temp1")
            self.assertEqual(values[0].source_code,"temp2")
            self.assertEqual(str(values[0].value),"26.5")

    def test_v2_kill_before_commit_redelivers_to_mapped_platform_point(self):
        first = self.start("before")
        self.wait_event(first,"receiver_ready")
        self.publish()
        self.wait_event(first,"before_commit")
        self.stop(first)
        second = self.start()
        self.wait_event(second,"receiver_ready")
        self.wait_event(second,"telemetry_stored")
        self.assert_one_mapped_value()

    def test_v2_kill_after_commit_does_not_duplicate_or_remap(self):
        first = self.start("after")
        self.wait_event(first,"receiver_ready")
        self.publish()
        self.wait_event(first,"after_commit")
        self.stop(first)
        second = self.start()
        self.wait_event(second,"receiver_ready")
        self.wait_event(second,"telemetry_duplicate")
        self.assert_one_mapped_value()

    def test_v2_offline_subscription_recovers_and_continues_new_messages(self):
        first = self.start()
        self.wait_event(first,"receiver_ready")
        self.stop(first)
        self.publish()
        second = self.start()
        ready = self.wait_event(second,"receiver_ready")
        self.assertTrue(ready["session_present"])
        self.wait_event(second,"telemetry_stored")
        self.assert_one_mapped_value()
