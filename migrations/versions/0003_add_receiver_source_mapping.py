"""移除固定電表快照，舊點位歷史與新來源映射統一使用 readings。"""
from datetime import timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _number(value):
    value = Decimal(value)
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if value == 0 else result


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _time(value):
    return value.astimezone(timezone.utc).isoformat()


def upgrade():
    connection = op.get_bind()
    for table in ("devices", "measurement_points"):
        if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE char_length(name)>100)")).scalar_one():
            raise RuntimeError(f"{table}.name 存在超過 100 字元的名稱，請先明確調整；不自動截斷")
    op.create_table("source_bindings",
        sa.Column("binding_id", sa.Uuid(), primary_key=True),
        sa.Column("receiver_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(512), nullable=False),
        sa.Column("source_gateway_id", sa.String(64), nullable=False),
        sa.Column("source_device_id", sa.String(64), nullable=False),
        sa.Column("source_code", sa.String(64), nullable=False),
        sa.Column("point_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["point_id"], ["measurement_points.point_id"], name="fk_bindings_point"),
        sa.UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "source_code",
                            name="uq_bindings_source"),
        sa.UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "point_id",
                            name="uq_bindings_stream_point"))
    op.create_index("ix_bindings_point", "source_bindings", ["point_id"])
    op.create_table("received_messages",
        sa.Column("receipt_id", sa.Uuid(), primary_key=True),
        sa.Column("receiver_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(512), nullable=False),
        sa.Column("source_gateway_id", sa.String(64), nullable=False),
        sa.Column("source_device_id", sa.String(64), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("readings_hash", sa.String(64), nullable=False),
        sa.Column("reading_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("receiver_id", "topic", "source_gateway_id", "source_device_id", "message_id",
                            name="uq_received_message_source"))
    op.add_column("readings", sa.Column("receipt_id", sa.Uuid(), nullable=True))
    op.add_column("readings", sa.Column("source_code", sa.String(64), nullable=True))
    connection = op.get_bind()
    units = {"voltage_v":"V", "current_a":"A", "power_w":"W", "energy_wh":"Wh"}
    # Migration 自帶穩定的舊格式轉換，不依賴未來可能改變的應用程式。
    for snapshot in connection.execute(sa.text("SELECT * FROM telemetry_readings")).mappings():
        device, message = snapshot["device_id"], snapshot["message_id"]
        receipt = uuid5(NAMESPACE_URL, f"okgo:legacy-v1:{device}:{message}")
        connection.execute(sa.text("""INSERT INTO devices(device_id,name,model_code)
            VALUES (:device,:display_name,'SIM-POWER-01') ON CONFLICT(device_id) DO NOTHING"""), {"device":device,"display_name":device})
        definitions = {"voltage_v":("電壓","V",Decimal("0.1")),
                       "current_a":("電流","A",Decimal("0.01")),
                       "power_w":("有功功率","W",Decimal("1")),
                       "energy_wh":("累積電量","Wh",Decimal("1"))}
        for code,(name,unit,resolution) in definitions.items():
            connection.execute(sa.text("""INSERT INTO measurement_points(point_id,device_id,code,name,unit,resolution)
                VALUES (:point,:device,:code,:name,:unit,:resolution)
                ON CONFLICT(device_id,code) DO NOTHING"""),
                {"point":uuid5(NAMESPACE_URL,f"okgo:legacy-point:{device}:{code}"),"device":device,
                 "code":code,"name":name,"unit":unit,"resolution":resolution})
            point = connection.execute(sa.text("SELECT * FROM measurement_points WHERE device_id=:device AND code=:code"),
                {"device":device,"code":code}).mappings().one()
            if point["unit"] != unit or point["resolution"] != resolution:
                raise RuntimeError("既有電表點位語意與快照不一致，拒絕移除快照；請先核對資料")
            # 補齊舊程式在 0002 升版後仍只寫快照的資料，避免移除時遺失量測值。
            connection.execute(sa.text("""INSERT INTO readings(point_id,message_id,device_id,acquired_at,received_at,value)
                VALUES (:point,:message,:device,:acquired,:received,:value)
                ON CONFLICT(point_id,message_id) DO NOTHING"""),
                {"point":point["point_id"],"message":message,"device":device,
                 "acquired":snapshot["acquired_at"],"received":snapshot["received_at"],"value":snapshot[code]})
        rows = connection.execute(sa.text("""SELECT r.*, p.code AS source_code FROM readings r
            JOIN measurement_points p ON p.point_id=r.point_id
            WHERE r.device_id=:device AND r.message_id=:message"""),
            {"device":device,"message":message}).mappings().all()
        content = {"schema_version":2, "message_id":str(message), "gateway_id":snapshot["gateway_id"],
            "device_id":device, "acquired_at":_time(snapshot["acquired_at"]),
            "readings":[{"code":code,"unit":units[code],"value":_number(snapshot[code]),
                         "acquired_at":_time(snapshot["acquired_at"])} for code in sorted(units)]}
        result = [{"point_id":str(row["point_id"]),"message_id":str(row["message_id"]),
                   "device_id":row["device_id"],"source_code":row["source_code"],
                   "value":_number(row["value"]),"acquired_at":_time(row["acquired_at"]),
                   "received_at":_time(row["received_at"])} for row in rows]
        connection.execute(sa.text("""INSERT INTO received_messages
            (receipt_id,receiver_id,topic,source_gateway_id,source_device_id,message_id,
             acquired_at,received_at,content_hash,readings_hash,reading_count)
            VALUES (:receipt,'legacy-v1',:topic,:gateway,:device,:message,:acquired,:received,:content,:result,:count)"""),
            {"receipt":receipt,"topic":f"okgo/demo/v1/devices/{device}/telemetry", "gateway":snapshot["gateway_id"],
             "device":device,"message":message,"acquired":snapshot["acquired_at"],"received":snapshot["received_at"],
             "content":_hash(content),"result":_hash(sorted(result,key=lambda item:item["point_id"])),"count":len(rows)})
        connection.execute(sa.text("""UPDATE readings r SET receipt_id=:receipt,source_code=p.code
            FROM measurement_points p WHERE r.point_id=p.point_id AND r.device_id=:device AND r.message_id=:message"""),
            {"receipt":receipt,"device":device,"message":message})
    op.alter_column("readings","receipt_id",nullable=False)
    op.alter_column("readings","source_code",nullable=False)
    op.drop_constraint("fk_readings_snapshot","readings",type_="foreignkey")
    op.drop_constraint("readings_pkey","readings",type_="primary")
    op.create_primary_key("readings_pkey","readings",["point_id","receipt_id"])
    op.create_foreign_key("fk_readings_receipt","readings","received_messages",["receipt_id"],["receipt_id"])
    op.drop_index("ix_readings_point_time",table_name="readings")
    op.create_index("ix_readings_point_time","readings",
                    ["point_id",sa.text("acquired_at DESC"),sa.text("message_id DESC"),sa.text("receipt_id DESC")])
    op.create_index("ix_readings_receipt","readings",["receipt_id"])
    op.drop_table("telemetry_readings")
    op.alter_column("devices", "name", existing_type=sa.Text(), type_=sa.String(100), existing_nullable=False)
    op.alter_column("measurement_points", "name", existing_type=sa.Text(), type_=sa.String(100), existing_nullable=False)
    op.drop_column("devices", "model_code")


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM received_messages UNION ALL SELECT 1 FROM source_bindings UNION ALL SELECT 1 FROM devices)")).scalar_one():
        raise RuntimeError("快照已移除且存在接收資料或綁定，無法無損還原原始暫存器，拒絕退版；請由備份還原")
    op.add_column("devices", sa.Column("model_code", sa.String(64), nullable=False))
    op.alter_column("devices", "name", existing_type=sa.String(100), type_=sa.Text(), existing_nullable=False)
    op.alter_column("measurement_points", "name", existing_type=sa.String(100), type_=sa.Text(), existing_nullable=False)
    op.create_table("telemetry_readings",
        sa.Column("device_id",sa.String(64),nullable=False),sa.Column("message_id",sa.Uuid(),nullable=False),
        sa.Column("schema_version",sa.Integer(),nullable=False),sa.Column("gateway_id",sa.String(64),nullable=False),
        sa.Column("acquired_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("received_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("raw_registers",postgresql.ARRAY(sa.Integer()),nullable=False),
        sa.Column("voltage_v",sa.Numeric(5,1),nullable=False),sa.Column("current_a",sa.Numeric(5,2),nullable=False),
        sa.Column("power_w",sa.Integer(),nullable=False),sa.Column("energy_wh",sa.BigInteger(),nullable=False),
        sa.Column("model_code",sa.String(64),nullable=True),sa.Column("source_data",postgresql.JSONB(),nullable=True),
        sa.PrimaryKeyConstraint("device_id","message_id"))
    op.drop_constraint("fk_readings_receipt","readings",type_="foreignkey")
    op.drop_constraint("readings_pkey","readings",type_="primary")
    op.create_primary_key("readings_pkey","readings",["point_id","message_id"])
    op.drop_index("ix_readings_receipt",table_name="readings")
    op.drop_index("ix_readings_point_time",table_name="readings")
    op.create_index("ix_readings_point_time","readings",["point_id",sa.text("acquired_at DESC"),sa.text("message_id DESC")])
    op.drop_column("readings","source_code")
    op.drop_column("readings","receipt_id")
    op.create_foreign_key("fk_readings_snapshot","readings","telemetry_readings",
                         ["device_id","message_id"],["device_id","message_id"])
    op.drop_table("received_messages")
    op.drop_index("ix_bindings_point",table_name="source_bindings")
    op.drop_table("source_bindings")
