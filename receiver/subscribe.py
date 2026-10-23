"""MQTT 訂閱與欄位驗證；完整契約驗證將分步補齊。"""
import argparse
from functools import partial
from datetime import datetime, timezone
import json
import math
import os
import sys
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from receiver.models import Telemetry
from storage.database import DEFAULT_DATABASE_URL, create_db_engine
from storage.telemetry import store_telemetry

TOPIC_FILTER = "okgo/demo/v1/devices/+/telemetry"


def handle_message(topic: str, payload: bytes, *, store) -> None:
    """處理單筆訊息；只攔截預期驗證錯誤，不吞掉程式缺陷。"""
    received_at = datetime.now(timezone.utc)
    try:
        model = Telemetry.model_validate_json(payload)
    except ValidationError as exc:
        # 不輸出原始 payload 或 Pydantic 的 input，避免錯誤紀錄夾帶任意內容。
        error = exc.errors(include_input=False, include_context=False, include_url=False)[0]
        code = "invalid_json" if error["type"] == "json_invalid" else "invalid_payload"
        print(json.dumps({
            "event": "telemetry_rejected", "code": code, "topic": topic,
            "received_at": received_at.isoformat(), "reason": error["msg"],
            "field": list(error["loc"]),
        }, ensure_ascii=False), file=sys.stderr, flush=True)
        return
    result = store(model, received_at=received_at)
    event_names = {"stored": "telemetry_stored", "duplicate": "telemetry_duplicate",
                   "conflict": "telemetry_conflict"}
    event = {
        "event": event_names[result], "topic": topic,
        "device_id": model.device_id, "message_id": model.message_id,
        "gateway_id": model.gateway_id, "acquired_at": model.acquired_at,
        "received_at": received_at.isoformat(),
    }
    if result == "stored":
        event["stored_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(event, ensure_ascii=False),
          file=sys.stderr if result == "conflict" else sys.stdout, flush=True)


class ReceiverError(Exception):
    """訂閱啟動或連線生命週期失敗。"""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def run_receiver(client, *, store, host="127.0.0.1", port=1883, timeout=5.0) -> int:
    """等待連線與訂閱確認後持續接收；結束時清理傳入的 client。"""
    if not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError("等待秒數必須大於 0 且不超過 5")
    connected, subscribed, stopped = Event(), Event(), Event()
    connection_rejected = False
    subscription_accepted = False
    callback_errors = []
    client.connect_timeout = timeout

    def on_connect(client, userdata, flags, reason_code, properties):
        nonlocal connection_rejected
        connection_rejected = reason_code.is_failure
        connected.set()

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        nonlocal subscription_accepted
        subscription_accepted = len(reason_codes) == 1 and reason_codes[0].value == 1
        subscribed.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        stopped.set()

    def on_message(client, userdata, message):
        try:
            handle_message(message.topic, message.payload, store=store)
        except Exception as exc:
            # 把非預期錯誤交回主執行緒拋出，不能讓背景執行緒死掉後假裝仍在接收。
            callback_errors.append(exc)
            stopped.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    try:
        try:
            rc = client.connect(host, port, keepalive=30)
        except OSError as exc:
            raise ReceiverError("broker_connection_failed", str(exc)) from exc
        if rc != mqtt.MQTT_ERR_SUCCESS or client.loop_start() != mqtt.MQTT_ERR_SUCCESS:
            raise ReceiverError("broker_connection_failed", "無法啟動 MQTT 連線或網路迴圈")
        if not connected.wait(timeout):
            raise ReceiverError("broker_connack_timeout", "未在期限內取得 CONNACK")
        if connection_rejected:
            raise ReceiverError("broker_connection_rejected", "Broker 拒絕連線")
        rc, mid = client.subscribe(TOPIC_FILTER, qos=1)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise ReceiverError("subscription_failed", f"subscribe rc={rc}")
        if not subscribed.wait(timeout):
            raise ReceiverError("subscription_timeout", "未在期限內取得 SUBACK")
        if not subscription_accepted:
            raise ReceiverError("subscription_rejected", "未獲授要求的 QoS 1")
        print(json.dumps({"event": "receiver_ready", "topic_filter": TOPIC_FILTER,
                          "qos": 1}), flush=True)
        # 使用有期限的等待，讓主執行緒能定期處理 Ctrl+C。
        while not stopped.wait(0.2):
            pass
        if callback_errors:
            raise callback_errors[0]
        raise ReceiverError("broker_disconnected", "Broker 連線已中斷；本階段不自動重連")
    except ReceiverError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "detail": str(exc),
                          "attempt_finished_at": datetime.now(timezone.utc).isoformat()},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            client.disconnect()
        finally:
            client.loop_stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="訂閱量測、驗證欄位並寫入 PostgreSQL")
    parser.add_argument("--broker-host", default="127.0.0.1")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--mqtt-timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    if not 1 <= args.broker_port <= 65535:
        parser.error("Broker port 必須介於 1～65535")
    if not math.isfinite(args.mqtt_timeout) or not 0 < args.mqtt_timeout <= 5:
        parser.error("等待秒數必須大於 0 且不超過 5")
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"rx-{uuid4().hex[:20]}", clean_session=True,
        protocol=mqtt.MQTTv311, reconnect_on_failure=False,
    )
    engine = create_db_engine(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    try:
        return run_receiver(client, store=partial(store_telemetry, engine),
                            host=args.broker_host, port=args.broker_port,
                            timeout=args.mqtt_timeout)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
