"""單筆量測儲存；故障恢復與 MQTT 確認由後續流程處理。"""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session

from receiver.models import Telemetry
from storage.models import TelemetryReading


StoreResult = Literal["stored", "duplicate", "conflict"]


def store_telemetry(engine: Engine, telemetry: Telemetry, *,
                    received_at: datetime) -> StoreResult:
    """提交一筆量測；重複不覆寫，DB 例外不轉成成功結果。"""
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("接收時間必須包含時區")
    measurement = telemetry.measurement
    reading = TelemetryReading(
        device_id=telemetry.device_id,
        message_id=UUID(telemetry.message_id),
        schema_version=telemetry.schema_version,
        gateway_id=telemetry.gateway_id,
        acquired_at=datetime.fromisoformat(telemetry.acquired_at.replace("Z", "+00:00")),
        received_at=received_at,
        raw_registers=list(telemetry.raw_registers),
        voltage_v=Decimal(str(measurement.voltage_v)),
        current_a=Decimal(str(measurement.current_a)),
        power_w=measurement.power_w,
        energy_wh=measurement.energy_wh,
    )
    values = reading.model_dump()
    # 由唯一鍵原子判斷是否新增，避免先查再新增造成並行競爭。
    statement = insert(TelemetryReading).values(**values).on_conflict_do_nothing(
        index_elements=["device_id", "message_id"],
    ).returning(TelemetryReading.message_id)
    with Session(engine) as session:
        inserted = session.execute(statement).scalar_one_or_none()
        if inserted is not None:
            result: StoreResult = "stored"
        else:
            existing = session.get(TelemetryReading, (reading.device_id, reading.message_id))
            if existing is None:
                raise RuntimeError("唯一鍵衝突後找不到原量測，無法確認儲存結果")
            # received_at 是每次接收的時間，不屬來源內容；保留首次值。
            same_content = all(
                getattr(existing, field) == value
                for field, value in values.items() if field != "received_at"
            )
            result = "duplicate" if same_content else "conflict"
        session.commit()
        return result
