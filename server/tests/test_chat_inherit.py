"""既往对话引用的来源追溯（2026-10-02）：直接继承 / 复制型向前追溯 / 无法匹配降级。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.chat.inherit import enrich_citations, resolve_inherited_citations
from app.config import settings
from app.models import (
    Chunk,
    Conversation,
    Document,
    DocumentStatus,
    Message,
    MessageRole,
    SourceType,
    User,
)


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def user(maker):
    async with maker() as s:
        u = User(username=f"inh-{uuid.uuid4().hex[:8]}", password_hash="x")
        s.add(u)
        await s.commit()
        return u


def _citations(n: int) -> list[dict]:
    return [
        {
            "document_id": str(uuid.uuid4()),
            "chunk_id": str(uuid.uuid4()),
            "document_name": f"来源{i + 1}",
            "heading_path": None,
            "page": None,
            "quote": "q",
            "source_url": f"https://example.com/{i + 1}",
        }
        for i in range(n)
    ]


async def _mk_message(
    maker, owner_id: uuid.UUID, conv_id: uuid.UUID, content: str, citations, at: datetime
) -> uuid.UUID:
    msg_id = uuid.uuid4()
    async with maker() as s:
        s.add(
            Message(
                id=msg_id,
                owner_user_id=owner_id,
                conversation_id=conv_id,
                role=MessageRole.assistant,
                content=content,
                citations=citations,
                created_at=at,
            )
        )
        await s.commit()
    return msg_id


async def test_inherit_direct_citations(maker, user):
    conv_id = uuid.uuid4()
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        await s.commit()
    reply = "SDD 的核心是规格 → 计划 → 任务 → 实现。[1]"
    cites = _citations(1)
    msg_id = await _mk_message(
        maker, user.id, conv_id, reply, cites, datetime.now(timezone.utc)
    )

    async with maker() as s:
        resolved = await resolve_inherited_citations(s, conv_id, f"问：SDD 是什么\n答：{reply}")
    assert resolved is not None
    assert resolved["message_id"] == str(msg_id)
    assert resolved["citations"] == cites


async def test_inherit_copy_forward_walks_back(maker, user):
    """复制型回答（无 citations、带旧标记）→ 继承更早一条引用数量足够的助手消息。"""
    conv_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        await s.commit()

    original_cites = _citations(3)
    await _mk_message(
        maker,
        user.id,
        conv_id,
        "资料2：CLDG-006 [2]；资料1 [1][2][3]。",
        original_cites,
        now - timedelta(minutes=10),
    )
    copied = "按收藏页面统计：井上誠 2 次 [3]；其余各 1 次 [1][2][3]。"
    copied_id = await _mk_message(maker, user.id, conv_id, copied, None, now)

    async with maker() as s:
        resolved = await resolve_inherited_citations(s, conv_id, f"问：谁最多\n答：{copied}")
    assert resolved is not None
    assert resolved["message_id"] == str(copied_id)
    assert resolved["citations"] == original_cites


async def test_enrich_citations_for_legacy_data(maker, user):
    """存量旧消息：读取时补全 conversation_id / message_id / inherited_citations（2026-10-02）。"""
    conv_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        await s.commit()

    original_cites = _citations(3)
    await _mk_message(
        maker, user.id, conv_id, "原始回答 [1][2][3]。", original_cites, now - timedelta(minutes=5)
    )
    copied = "复制回答 [1][2][3]。"
    copied_id = await _mk_message(maker, user.id, conv_id, copied, None, now)

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    async with maker() as s:
        s.add(
            Document(
                id=doc_id,
                owner_user_id=user.id,
                name="对话：t",
                format="conversation",
                size_bytes=0,
                sha256=uuid.uuid4().hex,
                status=DocumentStatus.indexed,
                source_type=SourceType.conversation,
                original_path="",
                conversation_id=conv_id,
            )
        )
        s.add(
            Chunk(
                id=chunk_id,
                owner_user_id=user.id,
                document_id=doc_id,
                content=f"问：q\n答：{copied}",
                embedding=[0.0] * settings.embedding_dim,
            )
        )
        await s.commit()

    # 旧存量引用的形态：无 conversation_id / message_id / inherited_citations
    citations = [
        {
            "document_id": str(doc_id),
            "chunk_id": str(chunk_id),
            "document_name": "对话：t",
            "heading_path": "第 1 轮",
            "page": None,
            "quote": None,
        }
    ]
    async with maker() as s:
        await enrich_citations(s, citations)
    assert citations[0]["conversation_id"] == str(conv_id)
    assert citations[0]["message_id"] == str(copied_id)
    assert citations[0]["inherited_citations"] == original_cites

    # 已补全的不重复处理；非对话来源不动
    await enrich_citations(None, None)
    upload_citation = [{"document_id": str(uuid.uuid4()), "chunk_id": None}]
    async with maker() as s:
        await enrich_citations(s, upload_citation)
    assert "conversation_id" not in upload_citation[0]


async def test_resolve_with_known_message_id(maker, user):
    """写时留痕：message_id 已知 → 跳过文本匹配直接定位（块内容对不上也能解析）。"""
    conv_id = uuid.uuid4()
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        await s.commit()
    cites = _citations(2)
    msg_id = await _mk_message(
        maker, user.id, conv_id, "原始回答 [1][2]。", cites, datetime.now(timezone.utc)
    )

    async with maker() as s:
        resolved = await resolve_inherited_citations(
            s, conv_id, "问：x\n答：与消息文本完全不同的内容", message_id=msg_id
        )
    assert resolved is not None
    assert resolved["message_id"] == str(msg_id)
    assert resolved["citations"] == cites


async def test_enrich_uses_chunk_provenance(maker, user):
    """新数据：chunk.provenance 存在 → enrich 直接取用（无需任何可匹配的消息）。"""
    conv_id = uuid.uuid4()
    doc_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    prov_cites = _citations(2)
    prov = {"message_id": str(uuid.uuid4()), "citations": prov_cites}
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        s.add(
            Document(
                id=doc_id,
                owner_user_id=user.id,
                name="对话：t",
                format="conversation",
                size_bytes=0,
                sha256=uuid.uuid4().hex,
                status=DocumentStatus.indexed,
                source_type=SourceType.conversation,
                original_path="",
                conversation_id=conv_id,
            )
        )
        s.add(
            Chunk(
                id=chunk_id,
                owner_user_id=user.id,
                document_id=doc_id,
                content="问：q\n答：没有任何可匹配的消息",
                embedding=[0.0] * settings.embedding_dim,
                provenance=prov,
            )
        )
        await s.commit()

    citations = [{"document_id": str(doc_id), "chunk_id": str(chunk_id), "quote": None}]
    async with maker() as s:
        await enrich_citations(s, citations)
    assert citations[0]["conversation_id"] == str(conv_id)
    assert citations[0]["message_id"] == prov["message_id"]
    assert citations[0]["inherited_citations"] == prov_cites


async def test_inherit_unmatched_or_no_markers(maker, user):
    conv_id = uuid.uuid4()
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title="t"))
        await s.commit()
    await _mk_message(
        maker, user.id, conv_id, "无标记的回答。", None, datetime.now(timezone.utc)
    )

    async with maker() as s:
        # 内容对不上任何消息 → None（降级纯文本）
        assert await resolve_inherited_citations(s, conv_id, "问：x\n答：完全不同的内容") is None
        # 能匹配但无标记、无来源 → message_id 有、citations None
        resolved = await resolve_inherited_citations(s, conv_id, "问：x\n答：无标记的回答。")
    assert resolved is not None
    assert resolved["citations"] is None
    assert resolved["message_id"]
