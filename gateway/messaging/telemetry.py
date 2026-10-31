"""將成功讀值快照轉成 MQTT 量測契約。"""
import re
from uuid import uuid4


IDENTIFIER_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def build_telemetry(snapshot: dict, *, device_id: str, gateway_id: str) -> dict:
    """替 read_snapshot 的成功結果建立新訊息；重送時沿用此結果。

    這裡只做組裝與識別碼檢查，不取代接收端完整資料驗證。
    """
    if snapshot.get("status") != "ok":
        raise ValueError("只有成功讀值的快照可以建立量測訊息")
    for name, value in (("device_id", device_id), ("gateway_id", gateway_id)):
        if not isinstance(value, str) or not 1 <= len(value) <= 64 or not IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"{name} 必須是 1～64 字元的小寫英數，並以連字號分隔")

    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        # 邏輯設備識別碼由設定提供，不沿用快照中的 Modbus Unit ID。
        "device_id": device_id,
        "gateway_id": gateway_id,
        "acquired_at": snapshot["acquired_at"],
        # 複製可變容器，避免原快照後續被修改時連帶改變待發訊息。
        "raw_registers": list(snapshot["raw_registers"]),
        "measurement": dict(snapshot["measurement"]),
    }
