"""add messages content trgm index (对话全文搜索)

Revision ID: d51a9c73e2b4
Revises: c14d7ab2e9f3
Create Date: 2026-10-02 16:30:00.000000

2026-10-02 对话搜索（FR-009 增强）：messages.content 建 pg_trgm GIN 索引，
中文子串 ILIKE 走索引（与 chunks.content 同机制，见 9d2b7c1e4f88 / research R9）。
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d51a9c73e2b4"
down_revision: str | Sequence[str] | None = "c14d7ab2e9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_messages_content_trgm",
        "messages",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_messages_content_trgm", table_name="messages")
