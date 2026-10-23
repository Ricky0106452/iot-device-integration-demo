"""${message}

版本：${up_revision}
前一版：${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    """套用本次資料庫變更；自動產生後仍須人工檢查。"""
    ${upgrades if upgrades else "pass"}


def downgrade():
    """撤回本次變更；執行前確認資料影響。"""
    ${downgrades if downgrades else "pass"}
