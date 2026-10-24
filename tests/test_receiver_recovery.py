"""真實 Broker + PostgreSQL 的 Receiver 重啟恢復；只允許獨立測試 Broker。"""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Thread
import time
import unittest
from uuid import uuid4

import paho.mqtt.client as mqtt
from sqlmodel import Session, select

from gateway.mqtt_publish import publish_telemetry
from storage.database import create_db_engine
from storage.device_setup import initialize_power_device
from storage.models import Device, MeasurementPoint, PointReading, TelemetryReading

ROOT = Path(__file__).resolve().parents[1]
# 暫停點只存在測試子程序，不在正式程式加入故障注入開關。
WORKER = '''
from functools import partial
import json, os
from threading import Event
import paho.mqtt.client as mqtt
from receiver.subscribe import run_receiver
from storage.database import create_db_engine
from storage.telemetry import store_telemetry
engine = create_db_engine(os.environ['IOT_TEST_DATABASE_URL'])
mode = os.environ['RECOVERY_PAUSE']
def store(model, *, received_at):
    if mode == 'before':
        print(json.dumps({'event': 'before_commit'}), flush=True)
        Event().wait()
    result = store_telemetry(engine, model, received_at=received_at)
    if mode == 'after':
        print(json.dumps({'event': 'after_commit'}), flush=True)
        Event().wait()
    return result
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
    client_id=os.environ['RECOVERY_CLIENT_ID'], clean_session=False,
    manual_ack=True, protocol=mqtt.MQTTv311, reconnect_on_failure=False)
try:
    raise SystemExit(run_receiver(client, store=store,
        port=int(os.environ['IOT_RECOVERY_BROKER_PORT'])))
finally:
    engine.dispose()
'''


@unittest.skipUnless(os.environ.get('IOT_TEST_DATABASE_URL') and
                     os.environ.get('IOT_RECOVERY_BROKER_PORT'),
                     '未設定獨立恢復測試 Broker 與測試 DB')
class ReceiverRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.port = int(os.environ['IOT_RECOVERY_BROKER_PORT'])
        if self.port == 1883:
            raise RuntimeError('不可使用展示 Broker；請建立獨立臨時 Broker')
        self.engine = create_db_engine(os.environ['IOT_TEST_DATABASE_URL'])
        self.device_id = 'recover-' + uuid4().hex
        self.client_id = 'recovery-' + uuid4().hex
        self.processes = []
        self.addCleanup(self.cleanup)
        initialize_power_device(self.engine, self.device_id)
        self.payload = json.loads((ROOT / 'docs/mqtt/telemetry.example.json').read_text(encoding='utf-8'))
        self.payload.update(device_id=self.device_id, message_id=str(uuid4()))

    def cleanup(self):
        for process in self.processes:
            self.stop(process)
        # 只清除此案例的持久工作階段與隨機設備資料。
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, clean_session=True)
        try:
            client.connect('127.0.0.1', self.port)
            client.loop(timeout=1)
            client.disconnect()
        finally:
            with Session(self.engine) as session:
                for entity in [PointReading, TelemetryReading, MeasurementPoint, Device]:
                    for row in session.exec(select(entity).where(entity.device_id == self.device_id)).all():
                        session.delete(row)
                    session.flush()
                session.commit()
            self.engine.dispose()

    def start(self, pause='none'):
        env = dict(os.environ, PYTHONIOENCODING='utf-8', RECOVERY_PAUSE=pause,
                   RECOVERY_CLIENT_ID=self.client_id)
        process = subprocess.Popen([sys.executable, '-u', '-c', WORKER], cwd=ROOT,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.processes.append(process)
        events = Queue()
        def read():
            for line in process.stdout:
                events.put(line)
            events.put(None)
        reader = Thread(target=read, daemon=True)
        reader.start()
        process.recovery_events, process.recovery_reader = events, reader
        process.recovery_pending = []
        return process

    def wait_event(self, process, event):
        for index, value in enumerate(process.recovery_pending):
            if value.get('event') == event:
                return process.recovery_pending.pop(index)
        deadline = time.monotonic() + 10
        lines = []
        while time.monotonic() < deadline:
            try:
                line = process.recovery_events.get(timeout=max(0.01, deadline - time.monotonic()))
            except Empty:
                break
            if line is None:
                break
            lines.append(line)
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('event') == event:
                return value
            process.recovery_pending.append(value)
        self.fail(f'Missing {event}: ' + ''.join(lines))

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.recovery_reader.join(timeout=2)
        process.stdout.close()

    def assert_rows(self, snapshots, points):
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(TelemetryReading).where(
                TelemetryReading.device_id == self.device_id)).all()), snapshots)
            self.assertEqual(len(session.exec(select(PointReading).where(
                PointReading.device_id == self.device_id)).all()), points)

    def publish(self):
        publish_telemetry(self.payload, port=self.port)

    def test_offline_backlog_then_new_message(self):
        first = self.start()
        self.assertFalse(self.wait_event(first, 'receiver_ready')['session_present'])
        self.stop(first)
        self.publish()
        second = self.start()
        # 積壓可能早於 ready 被處理，逐筆保留事件以免錯過。
        self.wait_event(second, 'telemetry_stored')
        self.assertTrue(self.wait_event(second, 'receiver_ready')['session_present'])
        self.assert_rows(1, 4)
        self.payload['message_id'] = str(uuid4())
        self.publish()
        self.wait_event(second, 'telemetry_stored')
        self.assert_rows(2, 8)

    def test_kill_before_commit_redelivers(self):
        first = self.start('before')
        self.wait_event(first, 'receiver_ready')
        self.publish()
        self.wait_event(first, 'before_commit')
        self.assert_rows(0, 0)
        self.stop(first)
        second = self.start()
        self.wait_event(second, 'telemetry_stored')
        self.assert_rows(1, 4)

    def test_kill_after_commit_redelivers_as_duplicate(self):
        first = self.start('after')
        self.wait_event(first, 'receiver_ready')
        self.publish()
        self.wait_event(first, 'after_commit')
        self.assert_rows(1, 4)
        self.stop(first)
        second = self.start()
        self.wait_event(second, 'telemetry_duplicate')
        self.assert_rows(1, 4)
