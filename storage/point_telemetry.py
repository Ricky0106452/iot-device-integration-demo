"""來源映射到統一 readings；收據僅保存身份、數量與指紋，和讀值同交易。"""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from storage.device_setup import DeviceConfigurationError
from storage.ingestion_integrity import fingerprint, readings_fingerprint
from storage.models import PointReading, MeasurementPoint, ReceivedMessage, SourceBinding


def existing_result(session, receipt, content_hash):
    if receipt.content_hash != content_hash:
        return "conflict"
    saved = session.exec(select(PointReading).where(PointReading.receipt_id == receipt.receipt_id)).all()
    if len(saved) != receipt.reading_count or readings_fingerprint(saved) != receipt.readings_hash:
        raise RuntimeError("接收收據與已保存點位值不一致，不能確認重送")
    return "duplicate"


def store_point_telemetry(engine: Engine, model, *, receiver_id: str, topic: str, received_at: datetime, resolve_points=None):
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("接收時間必須包含時區")
    content_hash = fingerprint(model.canonical_content())
    identity = dict(receiver_id=receiver_id, topic=topic, source_gateway_id=model.gateway_id,
                    source_device_id=model.device_id, message_id=UUID(model.message_id))
    predicates = [getattr(ReceivedMessage, key) == value for key, value in identity.items()]
    with Session(engine) as session:
        existing = session.exec(select(ReceivedMessage).where(*predicates)).first()
        if existing is not None:
            # 重送依第一次入庫的目的地檢查，不因後續重綁而再寫入其他平台點位。
            return existing_result(session, existing, content_hash)
        if resolve_points is None:
            bindings = session.exec(select(SourceBinding).where(
                SourceBinding.receiver_id == receiver_id, SourceBinding.topic == topic,
                SourceBinding.source_gateway_id == model.gateway_id,
                SourceBinding.source_device_id == model.device_id)).all()
            by_code = {binding.source_code: session.get(MeasurementPoint, binding.point_id)
                       for binding in bindings}
        else:
            # 僅供明確的 v1 相容轉接；v2 一律使用接收端自己的 source_bindings。
            by_code = resolve_points(session)
        receipt_id = uuid4()
        destinations = []
        for reading in model.readings:
            point = by_code.get(reading.code)
            if point is None:
                continue  # 平台可選擇只訂閱/映射來源訊息中的部分點位。
            if point is None or point.unit != reading.unit:
                raise DeviceConfigurationError("來源單位與平台點位不符，不自動轉換或改寫")
            destinations.append(PointReading(point_id=point.point_id, receipt_id=receipt_id,
                message_id=UUID(model.message_id), device_id=point.device_id, source_code=reading.code,
                value=reading.value, acquired_at=reading.acquired_at, received_at=received_at))
        if not destinations:
            return "unmapped"
        inserted = session.execute(insert(ReceivedMessage).values(
            receipt_id=receipt_id, **identity, acquired_at=model.acquired_at, received_at=received_at,
            content_hash=content_hash, readings_hash=readings_fingerprint(destinations),
            reading_count=len(destinations)).on_conflict_do_nothing(
            constraint="uq_received_message_source").returning(ReceivedMessage.receipt_id)).scalar_one_or_none()
        if inserted is None:
            existing = session.exec(select(ReceivedMessage).where(*predicates)).one()
            return existing_result(session, existing, content_hash)
        session.add_all(destinations)
        session.commit()
        return "stored"
