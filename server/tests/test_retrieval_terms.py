"""实测修复（2026-10-02）：中英混排拆词 + 网页标题参与关键词匹配。"""

import uuid
from datetime import datetime, timezone

import app.retrieval.search as search_module
from app.config import settings
from app.models import Chunk, Document, DocumentStatus, SourceType, User
from app.retrieval.search import _terms, hybrid_search


def test_terms_split_ascii_words_from_mixed_text() -> None:
    terms = _terms("简要概述一下我在upwork上面的资料", 8)
    assert "upwork" in [t.lower() for t in terms]

    terms2 = _terms("Next.js 教程 与 架构", 8)
    assert "Next.js" in terms2

    # 纯中文不受影响
    assert _terms("上周看过的文章", 8) == ["上周看过的文章"]


class _QueryEmbedding:
    """查询向量 = [1]*dim（与存储块的 [1,-1,...] 正交 → 纯向量分为 0）。"""

    async def embed(self, texts, on_progress=None):  # noqa: ANN001, ANN201
        return [[1.0] * settings.embedding_dim for _ in texts]


async def test_document_name_keyword_match_boosts_score(session, monkeypatch) -> None:
    monkeypatch.setattr(search_module, "get_embedding_provider", lambda: _QueryEmbedding())
    user = User(username=f"tn-{uuid.uuid4().hex[:8]}", password_hash="x")
    session.add(user)
    await session.flush()

    doc = Document(
        owner_user_id=user.id,
        name="Jason L. - Full-Stack AI Developer - Upwork Freelancer",
        format="html",
        size_bytes=1,
        sha256=str(uuid.uuid4()),
        status=DocumentStatus.indexed,
        source_type=SourceType.browser,
        original_path="p",
        source_url="https://www.upwork.com/freelancers/~test",
        site_name="www.upwork.com",
        last_captured_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    await session.flush()
    session.add(
        Chunk(
            document_id=doc.id,
            owner_user_id=user.id,
            content="导航栏文本 没有关键信息",
            embedding=[1.0, -1.0] * (settings.embedding_dim // 2),  # 与查询正交
        )
    )
    await session.commit()

    results = await hybrid_search(session, user.id, "upwork 资料")
    match = next((r for r in results if r.document_id == doc.id), None)
    assert match is not None, "标题命中应召回候选"
    assert match.score >= 0.05, "标题关键词应带来加成（向量分为 0）"
