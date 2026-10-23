"""使用 SQLModel metadata 比較與套用資料庫版本。"""
import os

from alembic import context

from storage.database import DEFAULT_DATABASE_URL, create_db_engine
from storage.models import TelemetryReading

config = context.config
target_metadata = TelemetryReading.metadata


def migrate_connection(connection):
    """使用既有連線執行 migration；測試可代入自己的交易。"""
    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        migrate_connection(supplied_connection)
    else:
        engine = create_db_engine(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
        try:
            with engine.connect() as connection:
                migrate_connection(connection)
        finally:
            engine.dispose()
