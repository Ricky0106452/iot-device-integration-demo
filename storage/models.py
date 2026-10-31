"""量測資料表 Entity；接收驗證仍使用 receiver.models。"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (CheckConstraint, DateTime, ForeignKeyConstraint,
                        Index, Numeric, UniqueConstraint, text)
from sqlmodel import Field, SQLModel


class Device(SQLModel, table=True):
    """平台管理的設備或邏輯群組；不承載來源協定與解碼模型。"""
    __tablename__ = "devices"

    device_id: str = Field(primary_key=True, max_length=64)
    name: str = Field(min_length=1, max_length=100)


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
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(max_length=32)
    resolution: Decimal = Field(sa_type=Numeric())


class PointReading(SQLModel, table=True):
    """統一的點位歷史；平台點位與來源訊息分離，不依賴電表快照。"""
    __tablename__ = "readings"
    __table_args__ = (
        ForeignKeyConstraint(["device_id", "point_id"],
            ["measurement_points.device_id", "measurement_points.point_id"], name="fk_readings_point"),
        ForeignKeyConstraint(["receipt_id"], ["received_messages.receipt_id"], name="fk_readings_receipt"),
        Index("ix_readings_point_time", "point_id", text("acquired_at DESC"), text("message_id DESC"), text("receipt_id DESC")),
        Index("ix_readings_receipt", "receipt_id"),
    )
    point_id: UUID = Field(primary_key=True)
    receipt_id: UUID = Field(primary_key=True)
    message_id: UUID
    device_id: str = Field(max_length=64)
    source_code: str = Field(max_length=64)
    acquired_at: datetime = Field(sa_type=DateTime(timezone=True))
    received_at: datetime = Field(sa_type=DateTime(timezone=True))
    value: Decimal = Field(sa_type=Numeric())


class SourceBinding(SQLModel, table=True):
    """接收端來源識別與平台點位的綁定，不含設備通訊細節。"""
    __tablename__ = "source_bindings"
    __table_args__ = (
        ForeignKeyConstraint(["point_id"], ["measurement_points.point_id"], name="fk_bindings_point"),
        UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "source_code",
                         name="uq_bindings_source"),
        UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "point_id",
                         name="uq_bindings_stream_point"),
        Index("ix_bindings_point", "point_id"),
    )
    binding_id: UUID = Field(primary_key=True)
    receiver_id: str = Field(max_length=64)
    topic: str = Field(max_length=512)
    source_gateway_id: str = Field(max_length=64)
    source_device_id: str = Field(max_length=64)
    source_code: str = Field(max_length=64)
    point_id: UUID


class ReceivedMessage(SQLModel, table=True):
    """最小接收收據；來源識別與完整性指紋，不保存 payload 或重複讀值。"""
    __tablename__ = "received_messages"
    __table_args__ = (
        UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "message_id",
                         name="uq_received_message_source"),
    )
    receipt_id: UUID = Field(primary_key=True)
    receiver_id: str = Field(max_length=64)
    topic: str = Field(max_length=512)
    source_gateway_id: str = Field(max_length=64)
    source_device_id: str = Field(max_length=64)
    message_id: UUID
    acquired_at: datetime = Field(sa_type=DateTime(timezone=True))
    received_at: datetime = Field(sa_type=DateTime(timezone=True))
    content_hash: str = Field(max_length=64)
    readings_hash: str = Field(max_length=64)
    reading_count: int = Field(ge=0)
