"""單次讀取設備，組成契約訊息並發布至 MQTT Broker。"""
import argparse
from datetime import datetime, timezone
import json
import math
import sys

from pymodbus.client import ModbusTcpClient

from gateway.mqtt_publish import PublishError, publish_telemetry
from gateway.publish_flow import acquire_and_publish
from gateway.telemetry import IDENTIFIER_PATTERN, build_telemetry


def create_parser(description="讀一次設備並等待 MQTT 發布確認"):
    """單次與持續模式共用相同連線參數。"""
    parser = argparse.ArgumentParser(description=description)
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


def run_once(args) -> int:
    """執行一輪採集與發布，每輪各自建立並清理通訊連線。"""
    def publish_snapshot(snapshot):
        message = build_telemetry(
            snapshot, device_id=args.device_id, gateway_id=args.gateway_id,
        )
        context = {key: message[key] for key in (
            "message_id", "device_id", "gateway_id", "acquired_at",
        )}
        context["topic"] = f"okgo/demo/v1/devices/{message['device_id']}/telemetry"
        # 採集紀錄寫 stderr，stdout 只在 Broker 確認後輸出成功結果。
        print(json.dumps({"event": "telemetry_acquired", **context}), file=sys.stderr, flush=True)
        try:
            publish_telemetry(
                message, host=args.broker_host, port=args.broker_port,
                timeout=args.mqtt_timeout,
            )
        except PublishError as exc:
            print(json.dumps({
                "status": "error", "code": exc.code, "detail": str(exc),
                "attempt_finished_at": datetime.now(timezone.utc).isoformat(),
                **context,
            }), file=sys.stderr, flush=True)
            raise
        print(json.dumps({
            "status": "ok", "event": "publish_acknowledged", **context,
            "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        }), flush=True)

    device = ModbusTcpClient(
        args.device_host, port=args.device_port,
        timeout=args.read_timeout, retries=0,
    )
    try:
        return acquire_and_publish(device, publish_snapshot, device_id=args.unit_id)
    except PublishError:
        return 1


def main(argv=None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    validate_options(parser, args)
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
