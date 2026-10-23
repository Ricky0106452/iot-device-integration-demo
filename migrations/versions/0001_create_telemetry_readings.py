"""建立量測資料表

版本：0001
前一版：
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """套用本次資料庫變更；自動產生後仍須人工檢查。"""
    # 已核對欄位型別與複合主鍵；此版本不匯入應用程式 Entity。
    op.create_table('telemetry_readings',
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('gateway_id', sa.String(length=64), nullable=False),
    sa.Column('acquired_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('raw_registers', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.Column('voltage_v', sa.Numeric(precision=5, scale=1), nullable=False),
    sa.Column('current_a', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('power_w', sa.Integer(), nullable=False),
    sa.Column('energy_wh', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('device_id', 'message_id')
    )


def downgrade():
    """撤回本次變更；執行前確認資料影響。"""
    # 已核對欄位型別與複合主鍵；此版本不匯入應用程式 Entity。
    op.drop_table('telemetry_readings')
