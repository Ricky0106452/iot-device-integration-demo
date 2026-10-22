"""Verify Paho -> local Broker -> Paho; not device telemetry ingestion."""
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt


def main():
    topic = f"okgo/demo/smoke/{uuid4()}"
    payload = b"mqtt-smoke-ok"
    subscribed = Event()
    received = Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            client.subscribe(topic, qos=1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if reason_codes and all(not code.is_failure for code in reason_codes):
            subscribed.set()

    def on_message(client, userdata, message):
        if message.topic == topic and message.payload == payload:
            received.set()

    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    subscriber.on_connect = on_connect
    subscriber.on_subscribe = on_subscribe
    subscriber.on_message = on_message
    try:
        subscriber.connect("127.0.0.1", 1883, keepalive=30)
        subscriber.loop_start()
        if not subscribed.wait(5):
            raise RuntimeError("Subscription was not acknowledged within 5 seconds")
        publisher.connect("127.0.0.1", 1883, keepalive=30)
        publisher.loop_start()
        info = publisher.publish(topic, payload, qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Publish failed: {info.rc}")
        info.wait_for_publish(timeout=5)
        if not info.is_published():
            raise RuntimeError("Broker publish acknowledgment timed out")
        if not received.wait(5):
            raise RuntimeError("Subscriber did not receive the expected payload")
        print(f"PASS: Paho publisher -> Mosquitto -> Paho subscriber; topic={topic}")
        print("QoS 1 publish acknowledged; matching payload received; retain=False")
    finally:
        for client in (publisher, subscriber):
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
