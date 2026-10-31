"""Gateway 唯一啟動入口：解析設定並管理待送佇列、背景補送與採集生命週期。"""
import argparse
from datetime import datetime, timezone
from functools import partial
import json
import math
from pathlib import Path
import sqlite3
import sys

from gateway.buffering.outbox import Outbox
from gateway.buffering.sender import OutboxSender
from gateway.messaging.publisher import publish_telemetry
from gateway.messaging.telemetry import IDENTIFIER_PATTERN
from gateway.polling import acquire_to_outbox, run_polling


def create_parser():
    """建立持續採集的設備與 Broker 參數。"""
    parser = argparse.ArgumentParser(description="持續讀取設備、保存並補送 MQTT；Ctrl+C 停止")
    parser.add_argument("--device-host", default="127.0.0.1")
    parser.add_argument("--device-port", type=int, default=1502)
    parser.add_argument("--unit-id", type=int, default=1)
    parser.add_argument("--device-id", default="meter-001")
    parser.add_argument("--gateway-id", default="gateway-001")
    parser.add_argument("--read-timeout", type=float, default=1.0)
    parser.add_argument("--broker-host", default="127.0.0.1")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--mqtt-timeout", type=float, default=5.0)
    return parser


def validate_options(parser, args) -> None:
    """開始採集前一次驗證設定，不在每輪重新解析命令列。"""
    for value in (args.device_port, args.broker_port):
        if not 1 <= value <= 65535:
            parser.error("連接埠必須介於 1～65535")
    for value in (args.device_id, args.gateway_id):
        if not 1 <= len(value) <= 64 or not IDENTIFIER_PATTERN.fullmatch(value):
            parser.error("識別碼必須為 1～64 字元的小寫英數，以連字號分隔")
    if not 1 <= args.unit_id <= 247:
        parser.error("Modbus Unit ID 必須介於 1～247")
    if not math.isfinite(args.read_timeout) or args.read_timeout <= 0:
        parser.error("設備讀取逾時必須是大於 0 的有限秒數")
    if not math.isfinite(args.mqtt_timeout) or not 0 < args.mqtt_timeout <= 5:
        parser.error("MQTT 等待秒數必須大於 0 且不超過 5")


def main(argv=None) -> int:
    parser = create_parser()
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
