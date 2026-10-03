"""add users session_epoch

Revision ID: 70eda961aa20
Revises: d51a9c73e2b4
Create Date: 2026-10-03 14:30:17.605663

2026-10-03 会话纪元（审计二期 A1）：cookie 携带 session_epoch，登出/吊销 +1 →
无状态签名 cookie 的服务端吊销；旧 cookie 随签名算法升级（SHA-256）一并失效。
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "70eda961aa20"
down_revision: str | Sequence[str] | None = "d51a9c73e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "session_epoch")
