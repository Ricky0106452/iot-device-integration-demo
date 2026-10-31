"""循序多設備排程；各設備按完成時間等待自己的間隔，不追趕過期輪次。"""
import json
import sys
from time import monotonic

from gateway.buffering.sender import context
from gateway.device.reader import create_client, read_device
from gateway.messaging.telemetry import build_telemetry, telemetry_topic


def acquire_to_outbox(settings, device, client, outbox, sender) -> int:
    sender.check()
    readings = read_device(client, device)
    if not readings:
        return 1
    message = build_telemetry(readings, device_id=device.device_id, gateway_id=settings.gateway_id)
    topic = telemetry_topic(settings.mqtt.topic_prefix, device.device_id)
    details = context(message, topic)
    print(json.dumps({"event": "telemetry_acquired", **details}), file=sys.stderr, flush=True)
    dropped = outbox.enqueue(topic, message)
    if dropped:
        print(json.dumps({"event": "outbox_discarded", "reason": "capacity_limit",
                          "dropped_count": dropped, "max_pending": settings.buffer.max_pending}),
              file=sys.stderr, flush=True)
    print(json.dumps({"event": "telemetry_buffered", "point_count": len(readings), **details}), flush=True)
    sender.wakeup.set()
    return 0


def run_polling(settings, outbox, sender, *, clock=monotonic, client_factory=create_client) -> int:
    clients = {}
    try:
        for channel in settings.channels:
            clients[channel.channel_id] = client_factory(channel)
        due = {device.device_id: clock() for device in settings.devices}
        while True:
            sender.check()
            for device in settings.devices:
                if clock() >= due[device.device_id]:
                    acquire_to_outbox(settings, device, clients[device.channel_id], outbox, sender)
                    due[device.device_id] = clock() + device.interval_seconds
            sender.wait(max(0, min(due.values()) - clock()))
    except KeyboardInterrupt:
        return 0
    finally:
        for client in clients.values():
            client.close()
