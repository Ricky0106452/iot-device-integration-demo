"""接收端平台點位與來源綁定；設定替換以 receiver_id 為範圍並在同一交易完成。"""
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from storage.device_setup import DeviceConfigurationError
from storage.models import Device, MeasurementPoint, SourceBinding


def configure_sources(engine, settings):
    with Session(engine) as session:
        # 不覆寫既有點位的名稱/單位/解析度；避免改設定後靜默改變歷史語意。
        for device in settings.platform_devices:
            session.execute(insert(Device).values(device_id=device.device_id, name=device.name)
                .on_conflict_do_nothing(index_elements=["device_id"]))
            for point in device.points:
                session.execute(insert(MeasurementPoint).values(point_id=uuid4(), device_id=device.device_id,
                    code=point.code, name=point.name, unit=point.unit, resolution=point.resolution)
                    .on_conflict_do_nothing(index_elements=["device_id", "code"]))
                saved = session.exec(select(MeasurementPoint).where(
                    MeasurementPoint.device_id == device.device_id, MeasurementPoint.code == point.code)).one()
                if saved.unit != point.unit or saved.resolution != point.resolution:
                    raise DeviceConfigurationError("平台點位單位/解析度已存在且不同，需明確安排轉換")
        points = {(point.device_id, point.code): point for point in session.exec(
            select(MeasurementPoint).where(MeasurementPoint.device_id.in_(
                [device.device_id for device in settings.platform_devices]))).all()}
        session.execute(delete(SourceBinding).where(SourceBinding.receiver_id == settings.receiver_id))
        session.add_all([SourceBinding(binding_id=uuid4(), receiver_id=settings.receiver_id,
            topic=binding.topic, source_gateway_id=binding.source_gateway_id,
            source_device_id=binding.source_device_id, source_code=binding.source_code,
            point_id=points[(binding.target_device_id, binding.target_point_code)].point_id)
            for binding in settings.bindings])
        session.commit()
