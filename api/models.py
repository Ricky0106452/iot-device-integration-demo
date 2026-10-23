"""API 回應 DTO，不直接把資料表 Entity 當成外部契約。"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MeasurementResponse(BaseModel):
    """已保存的四項量測，以 JSON number 回傳。"""
    voltage_v: float
    current_a: float
    power_w: int
    energy_wh: int


class TelemetryResponse(BaseModel):
    """一筆量測與平台首次接收時間。"""
    schema_version: int
    message_id: UUID
    device_id: str
    gateway_id: str
    acquired_at: datetime
    received_at: datetime
    raw_registers: list[int]
    measurement: MeasurementResponse
