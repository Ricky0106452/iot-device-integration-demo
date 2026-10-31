"""採集排程：設備快照先保存至本地待送佇列，再喚醒背景補送。"""
from collections.abc import Callable
import json
import math
import sys
from time import sleep

from pymodbus.client import ModbusTcpClient

from gateway.device.reader import acquire_and_handle
from gateway.buffering.sender import context
from gateway.messaging.telemetry import build_telemetry


def run_polling(acquire: Callable[[], int], *, interval: float, wait=None) -> int:
    """已處理的通訊失敗留待下一輪；不並行、不補跑、不吞程式缺陷。"""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("採集間隔必須是大於 0 的有限秒數")
    if wait is None:
        wait = sleep
    try:
        while True:
            # 單輪已記錄成功或失敗。下一輪是新採集，不是舊訊息重送。
            acquire()
            wait(interval)
    except KeyboardInterrupt:
        return 0


def acquire_to_outbox(args, outbox, sender) -> int:
    sender.check()

    def save(snapshot):
        message = build_telemetry(snapshot, device_id=args.device_id, gateway_id=args.gateway_id)
        topic = f"okgo/demo/v1/devices/{message['device_id']}/telemetry"
        details = context(message, topic)
        print(json.dumps({'event': 'telemetry_acquired', **details}), file=sys.stderr, flush=True)
        dropped = outbox.enqueue(topic, message)
        if dropped:
            print(json.dumps({'event': 'outbox_discarded', 'reason': 'capacity_limit',
                'dropped_count': dropped, 'max_pending': args.max_pending}),
                file=sys.stderr, flush=True)
        print(json.dumps({'event': 'telemetry_buffered', **details}), flush=True)
        sender.wakeup.set()

    device = ModbusTcpClient(args.device_host, port=args.device_port,
                            timeout=args.read_timeout, retries=0)
    return acquire_and_handle(device, save, device_id=args.unit_id)
