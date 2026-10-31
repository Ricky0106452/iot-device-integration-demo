"""量測查詢；只讀 DB，不啟動 MQTT 或執行 migration。"""
from contextlib import asynccontextmanager
import os
from pathlib import Path as FilePath
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from api.models import (DeviceResponse, PointHistoryResponse, PointResponse)
from receiver.models import IDENTIFIER_PATTERN
from storage.database import DEFAULT_DATABASE_URL, create_db_engine
from storage.models import Device, MeasurementPoint, PointReading


def get_session(request: Request):
    """每個請求獨立使用 Session，請求完成時關閉。"""
    with Session(request.app.state.engine) as session:
        yield session


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

    # 靜態展示頁只讀既有 API，不啟動採集或修改資料。
    web_directory = FilePath(__file__).resolve().parent / "web"
    app.mount("/assets", StaticFiles(directory=web_directory), name="assets")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(web_directory / "index.html")

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
        ).order_by(PointReading.acquired_at.desc(), PointReading.message_id.desc(), PointReading.receipt_id.desc())
          .offset(offset).limit(limit)).all()
        return {"point": point, "readings": readings}

    return app


app = create_app()
