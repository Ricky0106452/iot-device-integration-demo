"""組裝 v2 通用點位訊息；不混用 v1 固定電表欄位。"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4


def build_telemetry(readings: list[dict], *, device_id: str, gateway_id: str) -> dict:
    if not readings:
        raise ValueError("沒有成功讀取的點位，不建立空訊息")
    return {"schema_version": 2, "message_id": str(uuid4()),
            "device_id": device_id, "gateway_id": gateway_id,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "readings": deepcopy(readings)}


def telemetry_topic(prefix: str, device_id: str) -> str:
    return f"{prefix}/devices/{device_id}/telemetry"
