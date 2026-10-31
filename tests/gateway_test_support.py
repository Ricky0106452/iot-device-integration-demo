"""Gateway 測試配置；v1 Receiver 的歷史契約使用固定 fixture，不依賴 v2 Builder。"""
import json
from pathlib import Path


def settings_payload():
    return json.loads((Path(__file__).resolve().parents[1] / "appsettings.json").read_text(encoding="utf-8"))


def legacy_message(snapshot, *, device_id, gateway_id):
    from uuid import uuid4
    return {"schema_version": 1, "message_id": str(uuid4()), "device_id": device_id,
            "gateway_id": gateway_id, "acquired_at": snapshot["acquired_at"],
            "raw_registers": list(snapshot["raw_registers"]), "measurement": dict(snapshot["measurement"])}
