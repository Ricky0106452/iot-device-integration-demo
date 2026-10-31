"""以 Paho 發布已建立的契約訊息。"""
import json
import math
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt


class PublishError(Exception):
    """Broker 連線失敗或發布結果尚未確認。"""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def publish_telemetry(
    message: dict, *, topic=None, host="127.0.0.1", port=1883, timeout=5.0, client=None,
) -> None:
    """只在收到 QoS 1 確認後正常返回；傳入的 client 也會在結束時關閉。

    message 必須是 build_telemetry 的結果。不重新組裝或更新資料 ID／時間。
    client 參數供測試代入替身；一般呼叫由此函式建立獨立連線。
    """
    if not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError("MQTT 等待秒數必須大於 0 且不超過 5")
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if topic is None:
        topic = f"okgo/demo/v1/devices/{message['device_id']}/telemetry"
    if client is None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"gw-{uuid4().hex[:20]}",
            clean_session=True, protocol=mqtt.MQTTv311,
            reconnect_on_failure=False,
        )
    client.connect_timeout = timeout
    connected = Event()
    connection_rejected = False

    def on_connect(client, userdata, flags, reason_code, properties):
        nonlocal connection_rejected
        connection_rejected = reason_code.is_failure
        connected.set()

    client.on_connect = on_connect
    try:
        try:
            rc = client.connect(host, port, keepalive=30)
        except OSError as exc:
            raise PublishError("broker_connection_failed", str(exc)) from exc
        if rc != mqtt.MQTT_ERR_SUCCESS:
            raise PublishError("broker_connection_failed", f"connect rc={rc}")
        if client.loop_start() != mqtt.MQTT_ERR_SUCCESS:
            raise PublishError("broker_connection_failed", "無法啟動 MQTT 網路迴圈")
        if not connected.wait(timeout):
            raise PublishError("broker_connack_timeout", "未在期限內取得連線確認")
        if connection_rejected:
            raise PublishError("broker_connection_rejected", "Broker 拒絕連線")

        # 呼叫 publish 後，連線中斷或確認逾時都不能斷言 Broker 一定沒收到。
        try:
            info = client.publish(topic, payload=payload, qos=1, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise PublishError("publish_unconfirmed", f"publish rc={info.rc}")
            info.wait_for_publish(timeout=timeout)
            if not info.is_published():
                raise PublishError("publish_unconfirmed", "未在期限內取得 PUBACK")
        except (OSError, RuntimeError, ValueError) as exc:
            raise PublishError("publish_unconfirmed", str(exc)) from exc
    finally:
        try:
            client.disconnect()
        finally:
            client.loop_stop()
