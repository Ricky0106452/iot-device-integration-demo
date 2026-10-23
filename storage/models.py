"""量測資料表 Entity；接收驗證仍使用 receiver.models。"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Any

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint,
                        Index, Integer, Numeric, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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

    # 過渡 migration 0002 尚未強制新入庫流程填入；切換後再收緊。
    model_code: str | None = Field(default=None, max_length=64)
    source_data: dict[str, Any] | None = Field(default=None, sa_type=JSONB(none_as_null=True))


class Device(SQLModel, table=True):
    """設備實例；模型識別用來選擇驗證與點位映射。"""
    __tablename__ = "devices"

    device_id: str = Field(primary_key=True, max_length=64)
    name: str = Field(sa_type=Text)
    model_code: str = Field(max_length=64)


class MeasurementPoint(SQLModel, table=True):
    """設備提供的數值型量測項目，單位與刻度有明確語意。"""
    __tablename__ = "measurement_points"
    __table_args__ = (
        ForeignKeyConstraint(["device_id"], ["devices.device_id"], name="fk_points_device"),
        UniqueConstraint("device_id", "code", name="uq_points_device_code"),
        UniqueConstraint("device_id", "point_id", name="uq_points_device_point"),
        CheckConstraint("resolution > 0", name="ck_points_resolution_positive"),
    )

    point_id: UUID = Field(primary_key=True)
    device_id: str = Field(max_length=64)
    code: str = Field(max_length=64)
    name: str = Field(sa_type=Text)
    unit: str = Field(max_length=32)
    resolution: Decimal = Field(sa_type=Numeric())


class PointReading(SQLModel, table=True):
    """單一點位的歷史值；來源與點位必須屬於同一設備。"""
    __tablename__ = "readings"
    __table_args__ = (
        ForeignKeyConstraint(["device_id", "point_id"],
            ["measurement_points.device_id", "measurement_points.point_id"], name="fk_readings_point"),
        ForeignKeyConstraint(["device_id", "message_id"],
            ["telemetry_readings.device_id", "telemetry_readings.message_id"], name="fk_readings_snapshot"),
        Index("ix_readings_point_time", "point_id", text("acquired_at DESC"), text("message_id DESC")),
    )

    point_id: UUID = Field(primary_key=True)
    message_id: UUID = Field(primary_key=True)
    device_id: str = Field(max_length=64)
    acquired_at: datetime = Field(sa_type=DateTime(timezone=True))
    received_at: datetime = Field(sa_type=DateTime(timezone=True))
    # 不指定固定 scale，避免不同設備的合法小數被 DB 捨入。
    value: Decimal = Field(sa_type=Numeric())
