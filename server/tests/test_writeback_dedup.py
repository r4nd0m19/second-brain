"""回写写前查重（审计二期 C1）：库内已有高相似问答 → 跳过，防重复污染检索。"""

import uuid

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.chat import writeback
from app.config import settings
from app.models import Chunk, Conversation, Document, DocumentStatus, SourceType, User


def _vec(axis: int) -> list[float]:
    v = [0.0] * settings.embedding_dim
    v[axis] = 1.0
    return v


class _FakeEmbedding:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


def _enable_writeback(monkeypatch, maker, vector: list[float]) -> None:
    async def _reusable(_q: str, _a: str) -> bool:
        return True

    monkeypatch.setattr(writeback, "SessionLocal", maker)
    monkeypatch.setattr(writeback, "is_reusable_qa", _reusable)
    monkeypatch.setattr(writeback, "get_embedding_provider", lambda: _FakeEmbedding(vector))


async def _seed_chunk(maker, owner, conv, vector, content: str) -> None:
    async with maker() as s:
        s.add(User(id=owner, username=f"wb-{owner.hex[:8]}", password_hash="x"))
        await s.flush()
        s.add(Conversation(id=conv, owner_user_id=owner, title="测试会话"))
        await s.flush()
        doc = Document(
            id=uuid.uuid4(),
            owner_user_id=owner,
            name="对话：测试",
            format="conversation",
            size_bytes=0,
            sha256=f"conversation:{conv}",
            status=DocumentStatus.indexed,
            source_type=SourceType.conversation,
            original_path="",
            conversation_id=conv,
        )
        s.add(doc)
        await s.flush()
        s.add(Chunk(document_id=doc.id, owner_user_id=owner, content=content, embedding=vector))
        await s.commit()


async def _count(maker, owner) -> int:
    async with maker() as s:
        return (
            await s.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.owner_user_id == owner)
            )
        ) or 0


async def test_duplicate_writeback_skipped(monkeypatch, maker):
    owner, conv = uuid.uuid4(), uuid.uuid4()
    vec = _vec(0)
    await _seed_chunk(maker, owner, conv, vec, "问：旧问题\n答：旧答案")
    _enable_writeback(monkeypatch, maker, vec)  # 同向量 → 相似度 1.0 ≥ 0.95 → 跳过
    await writeback.writeback_exchange(owner, conv, "测试", "新问题", "新答案")
    assert await _count(maker, owner) == 1


async def test_distinct_writeback_kept(monkeypatch, maker):
    owner, conv = uuid.uuid4(), uuid.uuid4()
    await _seed_chunk(maker, owner, conv, _vec(0), "问：旧问题\n答：旧答案")
    _enable_writeback(monkeypatch, maker, _vec(1))  # 正交向量 → 相似度 0 → 正常写入
    await writeback.writeback_exchange(owner, conv, "测试", "新问题", "新答案")
    assert await _count(maker, owner) == 2
