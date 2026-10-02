"""add browser capture (documents extension columns + capture_tokens)

Revision ID: c14d7ab2e9f3
Revises: 9d2b7c1e4f88
Create Date: 2026-10-02 10:40:00.000000

F2：网页条目 = documents.source_type='browser' 的行（data-model.md）。
注：source_type 为非原生枚举 VARCHAR(32)；SQLAlchemy `create_constraint` 默认 False →
现存库无 CHECK 约束（2026-10-02 实核），新增枚举值 'browser' 只需改模型枚举，无需重建约束。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c14d7ab2e9f3"
down_revision: str | Sequence[str] | None = "9d2b7c1e4f88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # documents 扩展列（浏览器来源；全部 NULLABLE）
    op.add_column("documents", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("site_name", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("first_captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("last_captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("visit_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("snapshot_path", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("snapshot_bytes", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("snapshot_state", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("capture_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 同 URL 一条目（per-owner；FR-005）
    op.create_index(
        "uq_documents_owner_source_url",
        "documents",
        ["owner_user_id", "source_url"],
        unique=True,
        postgresql_where=sa.text("source_type = 'browser'"),
    )
    # 时间过滤检索 / "看过哪些"列表（R5）
    op.create_index("ix_documents_source_last_captured", "documents", ["source_type", "last_captured_at"])

    # 采集凭据（spec 实体 CaptureToken）
    op.create_table(
        "capture_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("scope", sa.Text(), nullable=False, server_default="capture"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_capture_tokens_owner_user_id", "capture_tokens", ["owner_user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_capture_tokens_owner_user_id", table_name="capture_tokens")
    op.drop_table("capture_tokens")
    op.drop_index("ix_documents_source_last_captured", table_name="documents")
    op.drop_index("uq_documents_owner_source_url", table_name="documents")
    for column in (
        "capture_id",
        "snapshot_state",
        "snapshot_bytes",
        "snapshot_path",
        "visit_count",
        "last_captured_at",
        "first_captured_at",
        "site_name",
        "source_url",
    ):
        op.drop_column("documents", column)
