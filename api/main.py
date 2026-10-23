"""量測查詢；只讀 DB，不啟動 MQTT 或執行 migration。"""
from contextlib import asynccontextmanager
import os
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from sqlmodel import Session, select

from api.models import (DeviceResponse, MeasurementResponse, PointHistoryResponse,
                        PointResponse, TelemetryResponse)
from receiver.models import IDENTIFIER_PATTERN
from storage.database import DEFAULT_DATABASE_URL, create_db_engine
from storage.models import Device, MeasurementPoint, PointReading, TelemetryReading


def get_session(request: Request):
    """每個請求獨立使用 Session，請求完成時關閉。"""
    with Session(request.app.state.engine) as session:
        yield session


def to_response(reading: TelemetryReading) -> TelemetryResponse:
    """共用量測回應映射，供最新值與歷史查詢使用。"""
    return TelemetryResponse(
        schema_version=reading.schema_version,
        message_id=reading.message_id, device_id=reading.device_id,
        gateway_id=reading.gateway_id, acquired_at=reading.acquired_at,
        received_at=reading.received_at, raw_registers=reading.raw_registers,
        measurement=MeasurementResponse(
            voltage_v=float(reading.voltage_v), current_a=float(reading.current_a),
            power_w=reading.power_w, energy_wh=reading.energy_wh,
        ),
    )


def create_app(*, database_url: str | None = None) -> FastAPI:
    """建立應用；啟動時建立 engine，結束時釋放連線池。"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = create_db_engine(
            database_url if database_url is not None
            else os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title="IoT Telemetry API", lifespan=lifespan)

    @app.get("/devices/{device_id}/telemetry/latest", response_model=TelemetryResponse,
             responses={404: {"description": "該設備沒有量測資料"}})
    def latest_telemetry(
        device_id: Annotated[str, Path(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)],
        session: Annotated[Session, Depends(get_session)],
    ):
        """依取得時間讀取最新一筆；同時間以訊息 ID 固定排序。"""
        statement = select(TelemetryReading).where(
            TelemetryReading.device_id == device_id,
        ).order_by(TelemetryReading.acquired_at.desc(),
                   TelemetryReading.message_id.desc()).limit(1)
        reading = session.exec(statement).first()
        if reading is None:
            raise HTTPException(status_code=404, detail="No telemetry found for device")
        return to_response(reading)


    @app.get("/telemetry", response_model=list[TelemetryResponse])
    def history_telemetry(
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        """分頁查詢所有設備的歷史量測，不必先提供設備 ID。"""
        statement = select(TelemetryReading).order_by(
            TelemetryReading.acquired_at.desc(), TelemetryReading.device_id.asc(),
            TelemetryReading.message_id.desc(),
        ).offset(offset).limit(limit)
        return [to_response(reading) for reading in session.exec(statement).all()]

    @app.get("/devices", response_model=list[DeviceResponse])
    def list_devices(
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        """列出已設定設備，讓使用者不必預先知道設備 ID。"""
        return session.exec(select(Device).order_by(Device.device_id)
                            .offset(offset).limit(limit)).all()

    @app.get("/devices/{device_id}/points", response_model=list[PointResponse],
             responses={404: {"description": "找不到設備"}})
    def list_points(
        device_id: Annotated[str, Path(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)],
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        """列出該設備的感測點、單位與解析度。"""
        if session.get(Device, device_id) is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return session.exec(select(MeasurementPoint).where(
            MeasurementPoint.device_id == device_id,
        ).order_by(MeasurementPoint.code).offset(offset).limit(limit)).all()

    @app.get("/points/{point_id}/readings", response_model=PointHistoryResponse,
             responses={404: {"description": "找不到感測點"}})
    def point_history(
        point_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        """查詢單一感測點的歷史，與設備種類的固定欄位無關。"""
        point = session.get(MeasurementPoint, point_id)
        if point is None:
            raise HTTPException(status_code=404, detail="Measurement point not found")
        readings = session.exec(select(PointReading).where(
            PointReading.point_id == point_id,
        ).order_by(PointReading.acquired_at.desc(), PointReading.message_id.desc())
          .offset(offset).limit(limit)).all()
        return {"point": point, "readings": readings}

    return app


app = create_app()
