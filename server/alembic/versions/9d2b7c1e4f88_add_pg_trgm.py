"""add pg_trgm index for keyword search

Revision ID: 9d2b7c1e4f88
Revises: 7c9e2f4a1b03
Create Date: 2026-10-02 00:30:00.000000

T033：中文关键词检索落地。zhparser 不在官方镜像（需自编译）→ 选 pg_trgm（环境决定，见 research R9）；
gin_trgm_ops 加速 ILIKE 子串匹配（≥3 字符模式走索引；短词回退扫描，压测记录见 R9）。
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9d2b7c1e4f88'
down_revision: str | Sequence[str] | None = '7c9e2f4a1b03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_content_trgm "
        "ON chunks USING gin (content gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_trgm")
    # 扩展保留（可能被其他对象引用）；如需移除：DROP EXTENSION pg_trgm
