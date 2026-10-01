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


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class AnswerSource(str, enum.Enum):
    kb = "kb"
    model_knowledge = "model_knowledge"
    prior_conversation = "prior_conversation"


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
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False
    )

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        sa.Index("ix_documents_owner_sha256", "owner_user_id", "sha256"),
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

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
