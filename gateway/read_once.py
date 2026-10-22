"""透過 Modbus TCP 單次讀值並解析；此模組尚不處理 MQTT 或資料儲存。"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sys

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from gateway.decoding import decode_measurement
from gateway.device_spec import MEASUREMENT_REGISTER_COUNT, MEASUREMENT_START_ADDRESS


def report_failure(code: str, detail: str) -> int:
    # 讀取失敗不代表量測為零，不可補零產生假資料。
    print(json.dumps({"status": "error", "code": code, "detail": detail,
                      "attempt_finished_at": datetime.now(timezone.utc).isoformat()}),
          file=sys.stderr)
    return 1


class AcquisitionError(Exception):
    """設備採集失敗，沒有可供後續處理的有效快照。"""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def read_snapshot(client: ModbusTcpClient, *, device_id: int) -> dict:
    """執行一次採集，不論成功或失敗都關閉傳入的設備 client。

    回傳的是內部讀值快照，尚未轉成 MQTT 契約要求的訊息格式。
    """
    try:
        if not client.connect():
            raise AcquisitionError("connection_failed", "Could not connect to the device")
        result = client.read_holding_registers(
            MEASUREMENT_START_ADDRESS,
            count=MEASUREMENT_REGISTER_COUNT,
            device_id=device_id,
        )
        acquired_at = datetime.now(timezone.utc).isoformat()
        if result.isError():
            raise AcquisitionError("modbus_exception", str(result))
        try:
            measurement = decode_measurement(result.registers)
        except ValueError as exc:
            raise AcquisitionError("invalid_measurement", str(exc))
        return {"status": "ok", "device_id": device_id,
                "acquired_at": acquired_at,
                "raw_registers": result.registers,
                "measurement": asdict(measurement)}
    except (ModbusException, OSError) as exc:
        # 更細的逾時與錯誤分類，待後續故障情境驗證後再補齊。
        raise AcquisitionError("communication_error", str(exc))
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one power-meter snapshot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1502)
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.timeout <= 0 or not 1 <= args.device_id <= 247:
        parser.error("port must be 1..65535, timeout > 0, device-id 1..247")

    client = ModbusTcpClient(args.host, port=args.port, timeout=args.timeout, retries=0)
    try:
        snapshot = read_snapshot(client, device_id=args.device_id)
    except AcquisitionError as exc:
        return report_failure(exc.code, str(exc))
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
