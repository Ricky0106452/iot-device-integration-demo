"""舊 v1 電表訊息的明確相容轉接；不再建立快照，與 v2 共用 readings。"""
from datetime import datetime
from decimal import Decimal

from receiver.point_models import PointTelemetry, PointValueMessage, utc_time
from storage.device_setup import POWER_POINTS, get_power_points
from storage.point_telemetry import store_point_telemetry


def store_telemetry(engine, telemetry, *, received_at: datetime):
    # 輸入已由 v1 Telemetry 驗證；舊 code 含底線，保留其語意但不放寬 v2 對外格式。
    acquired_at = utc_time(telemetry.acquired_at)
    message = PointTelemetry.model_construct(schema_version=2, message_id=telemetry.message_id,
        gateway_id=telemetry.gateway_id, device_id=telemetry.device_id, acquired_at=acquired_at,
        readings=[PointValueMessage.model_construct(code=code, unit=unit,
            acquired_at=acquired_at, value=Decimal(str(getattr(telemetry.measurement,code))))
            for code,(_,unit,_) in POWER_POINTS.items()])
    return store_point_telemetry(engine, message, receiver_id="legacy-v1",
        topic=f"okgo/demo/v1/devices/{telemetry.device_id}/telemetry", received_at=received_at,
        resolve_points=lambda session:get_power_points(session, telemetry.device_id))
