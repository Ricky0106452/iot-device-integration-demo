"""新增感測點結構並回填既有電表快照。

版本：0002
前一版：0001
本版為過渡結構，保留原電表欄位與舊版寫入相容性。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    """新增三張表，回填歷史資料；暫不強迫舊 receiver 寫入新欄位。"""
    op.create_table("devices",
        sa.Column("device_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("model_code", sa.String(64), nullable=False),
    )
    op.create_table("measurement_points",
        sa.Column("point_id", sa.Uuid(), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("resolution", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], name="fk_points_device"),
        sa.UniqueConstraint("device_id", "code", name="uq_points_device_code"),
        sa.UniqueConstraint("device_id", "point_id", name="uq_points_device_point"),
        sa.CheckConstraint("resolution > 0", name="ck_points_resolution_positive"),
    )
    op.add_column("telemetry_readings", sa.Column("model_code", sa.String(64), nullable=True))
    op.add_column("telemetry_readings", sa.Column("source_data", postgresql.JSONB(), nullable=True))
    op.create_table("readings",
        sa.Column("point_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("point_id", "message_id"),
        sa.ForeignKeyConstraint(["device_id", "point_id"],
            ["measurement_points.device_id", "measurement_points.point_id"], name="fk_readings_point"),
        sa.ForeignKeyConstraint(["device_id", "message_id"],
            ["telemetry_readings.device_id", "telemetry_readings.message_id"], name="fk_readings_snapshot"),
    )
    op.create_index("ix_readings_point_time", "readings",
                    ["point_id", sa.text("acquired_at DESC"), sa.text("message_id DESC")])
    op.execute("""
        INSERT INTO devices (device_id, name, model_code)
        SELECT DISTINCT device_id, device_id, 'SIM-POWER-01' FROM telemetry_readings
    """)
    op.execute("""
        INSERT INTO measurement_points (point_id, device_id, code, name, unit, resolution)
        SELECT gen_random_uuid(), d.device_id, p.code, p.name, p.unit, p.resolution
        FROM devices d CROSS JOIN (VALUES
            ('voltage_v', '電壓', 'V', 0.1::numeric),
            ('current_a', '電流', 'A', 0.01::numeric),
            ('power_w', '有功功率', 'W', 1::numeric),
            ('energy_wh', '累積電量', 'Wh', 1::numeric)
        ) AS p(code, name, unit, resolution)
    """)
    op.execute("""
        UPDATE telemetry_readings SET model_code = 'SIM-POWER-01',
            source_data = jsonb_build_object(
                'raw_registers', to_jsonb(raw_registers),
                'measurement', jsonb_build_object(
                    'voltage_v', voltage_v, 'current_a', current_a,
                    'power_w', power_w, 'energy_wh', energy_wh))
    """)
    op.execute("""
        INSERT INTO readings (point_id, message_id, device_id, acquired_at, received_at, value)
        SELECT p.point_id, t.message_id, t.device_id, t.acquired_at, t.received_at, v.value
        FROM telemetry_readings t CROSS JOIN LATERAL (VALUES
            ('voltage_v', t.voltage_v::numeric), ('current_a', t.current_a::numeric),
            ('power_w', t.power_w::numeric), ('energy_wh', t.energy_wh::numeric)
        ) AS v(code, value)
        JOIN measurement_points p ON p.device_id = t.device_id AND p.code = v.code
    """)


def downgrade():
    """只允許舊欄位足以還原來源的退版，避免丟失新模型或不同數值。"""
    connection = op.get_bind()
    unsupported = connection.execute(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM devices WHERE model_code <> 'SIM-POWER-01'
            UNION ALL
            SELECT 1 FROM telemetry_readings
            WHERE model_code IS NOT NULL AND model_code <> 'SIM-POWER-01'
            UNION ALL
            SELECT 1 FROM telemetry_readings
            WHERE source_data IS NOT NULL AND source_data IS DISTINCT FROM jsonb_build_object(
                'raw_registers', to_jsonb(raw_registers),
                'measurement', jsonb_build_object('voltage_v', voltage_v, 'current_a', current_a,
                    'power_w', power_w, 'energy_wh', energy_wh))
            UNION ALL
            SELECT 1 FROM readings r
            JOIN measurement_points p ON p.point_id = r.point_id
            JOIN telemetry_readings t ON t.device_id = r.device_id AND t.message_id = r.message_id
            WHERE r.acquired_at <> t.acquired_at OR r.received_at <> t.received_at
               OR r.value IS DISTINCT FROM CASE p.code
                    WHEN 'voltage_v' THEN t.voltage_v::numeric
                    WHEN 'current_a' THEN t.current_a::numeric
                    WHEN 'power_w' THEN t.power_w::numeric
                    WHEN 'energy_wh' THEN t.energy_wh::numeric END
            UNION ALL
            SELECT 1 FROM measurement_points
            WHERE (code, unit, resolution) NOT IN (
                ('voltage_v', 'V', 0.1::numeric), ('current_a', 'A', 0.01::numeric),
                ('power_w', 'W', 1::numeric), ('energy_wh', 'Wh', 1::numeric))
        )
    """)).scalar_one()
    if unsupported:
        raise RuntimeError("新模型或點位資料無法由舊電表欄位還原，拒絕退版；請先備份並安排資料轉換")
    op.drop_index("ix_readings_point_time", table_name="readings")
    op.drop_table("readings")
    op.drop_column("telemetry_readings", "source_data")
    op.drop_column("telemetry_readings", "model_code")
    op.drop_table("measurement_points")
    op.drop_table("devices")
