"""API 回應 DTO，不直接把資料表 Entity 當成外部契約。"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DeviceResponse(BaseModel):
    """供使用者探索的設備清單項目。"""
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    name: str


class PointResponse(BaseModel):
    """感測點名稱、單位與刻度；十進位資料回傳字串以保留精度。"""
    model_config = ConfigDict(from_attributes=True)

    point_id: UUID
    device_id: str
    code: str
    name: str
    unit: str
    resolution: Decimal


class PointValueResponse(BaseModel):
    """單一點位歷史值，不包含原始封包或整份採集快照。"""
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    acquired_at: datetime
    received_at: datetime
    value: Decimal


class PointHistoryResponse(BaseModel):
    """固定的點位資訊與本次查詢的歷史頁面。"""
    point: PointResponse
    readings: list[PointValueResponse]
