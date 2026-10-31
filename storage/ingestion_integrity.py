"""訊息與點位結果的穩定指紋；收據不重複保存量測內容。"""
from datetime import timezone
from decimal import Decimal
from hashlib import sha256
import json


def number(value):
    value = Decimal(value)
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if value == 0 else result


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def readings_fingerprint(rows):
    values = [{"point_id":str(row.point_id), "message_id":str(row.message_id),
               "device_id":row.device_id, "source_code":row.source_code,
               "value":number(row.value),
               "acquired_at":row.acquired_at.astimezone(timezone.utc).isoformat(),
               "received_at":row.received_at.astimezone(timezone.utc).isoformat()} for row in rows]
    return fingerprint(sorted(values, key=lambda item:item["point_id"]))
