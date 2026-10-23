"""電表設備與點位的明確初始化；接收訊息時不自動猜測設定。"""
import argparse
from decimal import Decimal
import os
import re
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from receiver.models import IDENTIFIER_PATTERN
from storage.database import DEFAULT_DATABASE_URL, create_db_engine
from storage.models import Device, MeasurementPoint

POWER_MODEL = "SIM-POWER-01"
POWER_POINTS = {
    "voltage_v": ("電壓", "V", Decimal("0.1")),
    "current_a": ("電流", "A", Decimal("0.01")),
    "power_w": ("有功功率", "W", Decimal("1")),
    "energy_wh": ("累積電量", "Wh", Decimal("1")),
}


class DeviceConfigurationError(ValueError):
    """設備或點位設定不足以解讀本次電表訊息。"""


def get_power_points(session: Session, device_id: str) -> dict[str, MeasurementPoint]:
    """核對已設定模型、點位集合、單位與刻度，不變更任何設定。"""
    device = session.get(Device, device_id)
    if device is None or device.model_code != POWER_MODEL:
        raise DeviceConfigurationError("設備尚未設定為 SIM-POWER-01 電表")
    points = session.exec(select(MeasurementPoint).where(
        MeasurementPoint.device_id == device_id)).all()
    mapped = {point.code: point for point in points}
    if set(mapped) != set(POWER_POINTS):
        raise DeviceConfigurationError("電表必須預先設定完整且正確的四個量測點位")
    for code, (_, unit, resolution) in POWER_POINTS.items():
        if mapped[code].unit != unit or mapped[code].resolution != resolution:
            raise DeviceConfigurationError(f"點位 {code} 的單位或解析度與設備模型不符")
    return mapped


def initialize_power_device(engine: Engine, device_id: str) -> None:
    """明確建立設備與四個標準點位；重跑不更動原有名稱、ID 或語意。"""
    if not 1 <= len(device_id) <= 64 or re.fullmatch(IDENTIFIER_PATTERN, device_id) is None:
        raise ValueError("設備 ID 必須符合現有識別碼格式，長度 1～64")
    with Session(engine) as session:
        session.execute(insert(Device).values(
            device_id=device_id, name=device_id, model_code=POWER_MODEL,
        ).on_conflict_do_nothing(index_elements=["device_id"]))
        device = session.get(Device, device_id)
        if device.model_code != POWER_MODEL:
            raise DeviceConfigurationError("不能把已設定的其他模型覆寫為電表")
        for code, (name, unit, resolution) in POWER_POINTS.items():
            session.execute(insert(MeasurementPoint).values(
                point_id=uuid4(), device_id=device_id, code=code, name=name,
                unit=unit, resolution=resolution,
            ).on_conflict_do_nothing(index_elements=["device_id", "code"]))
        get_power_points(session, device_id)
        session.commit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="初始化已知電表設備與四個標準感測點")
    parser.add_argument("--device-id", default="meter-001")
    args = parser.parse_args(argv)
    engine = create_db_engine(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    try:
        initialize_power_device(engine, args.device_id)
    finally:
        engine.dispose()
    print(f"已確認設備 {args.device_id} 與四個電表點位設定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
