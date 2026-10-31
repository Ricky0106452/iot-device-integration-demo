"""設備採集：每輪讀取 Modbus、解析快照並關閉設備連線。"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from collections.abc import Callable
import sys

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from gateway.device.decoding import decode_measurement
from gateway.device.spec import MEASUREMENT_REGISTER_COUNT, MEASUREMENT_START_ADDRESS


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


def acquire_and_handle(
    client: ModbusTcpClient,
    handle_snapshot: Callable[[dict], None],
    *,
    device_id: int,
) -> int:
    """只有成功讀取並解析的快照，才交給處理函式。

    呼叫端傳入處理函式，例如組裝訊息並保存至本地待送佇列。
    回傳 0 只表示處理函式正常結束，不代表 Broker 已收到。
    處理函式的例外會向外傳遞，不將處理失敗誤分類成設備採集失敗。
    """
    try:
        snapshot = read_snapshot(client, device_id=device_id)
    except AcquisitionError as exc:
        return report_failure(exc.code, str(exc))
    handle_snapshot(snapshot)
    return 0
