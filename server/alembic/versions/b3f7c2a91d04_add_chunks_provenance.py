"""add chunks provenance

Revision ID: b3f7c2a91d04
Revises: 70eda961aa20
Create Date: 2026-10-03 16:10:00.000000

2026-10-03 三期 P1（写时留痕）：对话回写块记录溯源结果
{"message_id": str, "citations": [...] | None} —— 读取时零匹配取用，
不再依赖文本匹配启发式（存量数据由回填脚本补写，启发式仅兜底）。
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "b3f7c2a91d04"
down_revision: str | Sequence[str] | None = "70eda961aa20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chunks", sa.Column("provenance", JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chunks", "provenance")
