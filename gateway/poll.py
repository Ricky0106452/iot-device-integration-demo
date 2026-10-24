"""持續採集並保存單台設備量測，獨立執行緒補送已保存訊息。"""
from collections.abc import Callable
import math
from datetime import datetime, timezone
from functools import partial
import json
from pathlib import Path
import sqlite3
import sys
from time import sleep

from pymodbus.client import ModbusTcpClient

from gateway.publish_once import create_parser, validate_options
from gateway.publish_flow import acquire_and_publish
from gateway.mqtt_publish import publish_telemetry
from gateway.outbox import Outbox
from gateway.outbox_sender import OutboxSender, context
from gateway.telemetry import build_telemetry


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
    return acquire_and_publish(device, save, device_id=args.unit_id)


def main(argv=None) -> int:
    parser = create_parser("持續讀取設備並發布 MQTT；Ctrl+C 停止")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="每輪完成後等待的秒數，預設 5 秒")
    parser.add_argument('--outbox', help='SQLite 檔案；預設 data/<gateway-id>-outbox.sqlite3')
    parser.add_argument('--max-pending', type=int, default=10000, help='待送上限，預設 10000 筆')
    parser.add_argument('--retry-interval', type=float, default=5.0, help='發布失敗後等待秒數，預設 5 秒')
    args = parser.parse_args(argv)
    validate_options(parser, args)
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("採集間隔必須是大於 0 的有限秒數")
    if args.outbox == ':memory:':
        parser.error('待送佇列必須使用磁碟檔案')
    if args.max_pending <= 0:
        parser.error('待送容量必須大於零')
    if not math.isfinite(args.retry_interval) or args.retry_interval <= 0:
        parser.error('重試間隔必須是大於零的有限秒數')
    path = args.outbox if args.outbox is not None else Path('data') / f'{args.gateway_id}-outbox.sqlite3'
    try:
        with Outbox(path, max_pending=args.max_pending) as outbox:
            publisher = partial(publish_telemetry, host=args.broker_host,
                                port=args.broker_port, timeout=args.mqtt_timeout)
            with OutboxSender(outbox, publisher, retry_interval=args.retry_interval) as sender:
                return run_polling(lambda: acquire_to_outbox(args, outbox, sender),
                                   interval=args.interval, wait=sender.wait)
    except (sqlite3.Error, OSError) as exc:
        print(json.dumps({'status': 'error', 'code': 'outbox_storage_failed', 'detail': str(exc),
            'attempt_finished_at': datetime.now(timezone.utc).isoformat()}),
            file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
