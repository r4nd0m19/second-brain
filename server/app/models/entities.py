"""实体模型 —— 字段与 specs/001-core-qa/data-model.md 逐项对应。"""

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models.base import Base, OwnerMixin, TimestampMixin


class DocumentStatus(str, enum.Enum):
    processing = "processing"
    indexed = "indexed"
    unparseable = "unparseable"


class SourceType(str, enum.Enum):
    upload = "upload"
    conversation = "conversation"
    browser = "browser"
    note = "note"  # MCP「写入回存」笔记（2026-10-02）：资料级文档，标准入库管线


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class AnswerSource(str, enum.Enum):
    kb = "kb"
    model_knowledge = "model_knowledge"
    prior_conversation = "prior_conversation"
    web = "web"  # 联网检索作答（F4，2026-10-02）：依据即时搜索结果


def _enum(enum_cls) -> sa.Enum:
    """非原生 Enum（VARCHAR + CHECK）：避免 PG 原生类型迁移的麻烦。"""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)


class Document(Base, OwnerMixin, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    format: Mapped[str] = mapped_column(sa.Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus), nullable=False, default=DocumentStatus.processing
    )
    status_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(
        _enum(SourceType), nullable=False, default=SourceType.upload
    )
    original_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )  # 回写类资料（source_type=conversation）所属会话（FR-008）；对话删除时级联清理
    parse_hint: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True
    )  # 解析质量提示（如表格较多→建议深度解析；R7）

    # ── 浏览器采集扩展列（F2；仅 source_type=browser 使用，全部 NULLABLE，见 data-model.md）──
    source_url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # 规范化 URL（去 fragment）
    site_name: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # 域名（host）
    first_captured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_captured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    visit_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # 访问次数（FR-005）
    snapshot_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # {owner}/{doc}/snapshot.html.gz
    snapshot_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)  # 压缩后字节数
    snapshot_state: Mapped[str | None] = mapped_column(
        sa.Text, nullable=True
    )  # kept / skipped_oversize / skipped_error
    capture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # 最近一次采集事件幂等键（重试去重）
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        sa.Index("ix_documents_owner_sha256", "owner_user_id", "sha256"),
        # F2：同 URL 一条目（per-owner；FR-005）
        sa.Index(
            "uq_documents_owner_source_url",
            "owner_user_id",
            "source_url",
            unique=True,
            postgresql_where=sa.text("source_type = 'browser'"),
        ),
        # F2：时间过滤检索 / "看过哪些"列表（R5）
        sa.Index("ix_documents_source_last_captured", "source_type", "last_captured_at"),
    )


class Chunk(Base, OwnerMixin, TimestampMixin):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)  # Docling HybridChunker 标题路径
    page: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    chapter: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    paragraph: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        sa.Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sa.Index(
            "ix_chunks_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),  # 中文关键词检索（T033；pg_trgm，见 research R9）
    )


class Conversation(Base, OwnerMixin, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False, default="新对话")  # 默认取首问前 20 字（业务层）

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base, OwnerMixin, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_type: Mapped[AnswerSource | None] = mapped_column(_enum(AnswerSource), nullable=True)  # 仅 assistant
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{document_id, chunk_id, heading_path, page, quote}]
    related_hints: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 弱相关提示（FR-007）
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # token 用量与费用估算（FR-017）

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        sa.Index(
            "ix_messages_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),  # 对话全文搜索（2026-10-02；pg_trgm，与 chunks 同机制）
    )


class CaptureToken(Base, TimestampMixin):
    """采集凭据（F2 spec 实体 CaptureToken）：哈希存储、可吊销、scope 边界（research R2）。"""

    __tablename__ = "capture_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)  # 设备/用途标识（如 "Windows Chrome"）
    prefix: Mapped[str] = mapped_column(sa.Text, nullable=False)  # 明文前缀（列表识别用）
    token_hash: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)  # sha256；明文仅创建时返回
    scope: Mapped[str] = mapped_column(
        sa.Text, nullable=False, default="capture", server_default="capture"
    )  # 权限边界（为 B1 等未来采集器复用留路）
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
