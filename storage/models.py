"""量測資料表 Entity；接收驗證仍使用 receiver.models。"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class TelemetryReading(SQLModel, table=True):
    """一筆量測；複合主鍵防止同設備同資料 ID 重複新增。"""
    __tablename__ = "telemetry_readings"

    device_id: str = Field(primary_key=True, max_length=64)
    message_id: UUID = Field(primary_key=True)
    schema_version: int
    gateway_id: str = Field(max_length=64)
    acquired_at: datetime = Field(sa_type=DateTime(timezone=True))
    received_at: datetime = Field(sa_type=DateTime(timezone=True))
    raw_registers: list[int] = Field(sa_type=ARRAY(Integer))
    # 小數位依設備倍率保存；這不是正常工作範圍的拒收門檻。
    voltage_v: Decimal = Field(max_digits=5, decimal_places=1)
    current_a: Decimal = Field(max_digits=5, decimal_places=2)
    power_w: int
    # UInt32 的最大電量大於 PostgreSQL INTEGER 上限，使用 BIGINT。
    energy_wh: int = Field(sa_type=BigInteger)
