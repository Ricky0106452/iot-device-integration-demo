"""資料庫 engine；結構變更一律由 Alembic migration 管理。"""
from sqlalchemy import Engine
from sqlmodel import create_engine

# 固定示範帳密只用於 localhost Compose；其他環境透過 DATABASE_URL 指定。
DEFAULT_DATABASE_URL = "postgresql+psycopg://iot_demo:iot_demo_local@127.0.0.1:15433/iot_demo"


def create_db_engine(database_url: str) -> Engine:
    """建立 engine，不在匯入模組時連線或建表。"""
    return create_engine(database_url, connect_args={"connect_timeout": 3})
