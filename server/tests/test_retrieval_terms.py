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


def test_terms_drop_pure_numeric_tokens() -> None:
    """2026-10-02 实测："37" 词界命中 SVG 坐标 "37.8399" 造成假性加成 → 纯数字词项剔除。"""
    terms = _terms("请计算 463718 乘以 37 等于多少，并给出步骤", 8)
    assert "463718" not in terms and "37" not in terms
    assert "乘以" in terms
    # 含字母的混合词项保留（GPT-4 / time scale 等）
    assert "GPT-4" in _terms("GPT-4 的价格", 8)
    assert "scale" in [t.lower() for t in _terms("time scale 0.5 时", 8)]


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


async def test_ascii_term_word_boundary_no_substring_false_positive(session, monkeypatch) -> None:
    """2026-10-02 实测修复：ASCII 词按词边界匹配——'face' 不应命中 'interface'。"""
    monkeypatch.setattr(search_module, "get_embedding_provider", lambda: _QueryEmbedding())
    user = User(username=f"tn-{uuid.uuid4().hex[:8]}", password_hash="x")
    session.add(user)
    await session.flush()

    doc_face = Document(
        owner_user_id=user.id, name="Face 工具", format="txt", size_bytes=1,
        sha256=str(uuid.uuid4()), status=DocumentStatus.indexed,
        source_type=SourceType.upload, original_path="p",
    )
    doc_iface = Document(
        owner_user_id=user.id, name="Interface 设计指南", format="txt", size_bytes=1,
        sha256=str(uuid.uuid4()), status=DocumentStatus.indexed,
        source_type=SourceType.upload, original_path="p",
    )
    session.add_all([doc_face, doc_iface])
    await session.flush()
    session.add_all(
        [
            Chunk(document_id=doc_face.id, owner_user_id=user.id, content="无关正文",
                  embedding=[1.0, -1.0] * (settings.embedding_dim // 2)),
            Chunk(document_id=doc_iface.id, owner_user_id=user.id, content="无关正文",
                  embedding=[1.0, -1.0] * (settings.embedding_dim // 2)),
        ]
    )
    await session.commit()

    results = await hybrid_search(session, user.id, "face 相关")
    scores = {r.document_id: r.score for r in results}
    assert scores.get(doc_face.id, 0) >= settings.retrieval_keyword_boost  # 词边界命中
    assert scores.get(doc_iface.id, 0) < settings.retrieval_keyword_boost  # interface 不加成


async def test_ascii_name_flexible_separators(session, monkeypatch) -> None:
    """2026-10-02：人名连写/分写互通——「我是jasonL」应命中 "Jason L. …"（词内弹性分隔）。"""
    monkeypatch.setattr(search_module, "get_embedding_provider", lambda: _QueryEmbedding())
    user = User(username=f"tn-{uuid.uuid4().hex[:8]}", password_hash="x")
    session.add(user)
    await session.flush()

    doc_hit = Document(
        owner_user_id=user.id, name="Jason L. - Full-Stack AI Developer | Next.js",
        format="txt", size_bytes=1, sha256=str(uuid.uuid4()), status=DocumentStatus.indexed,
        source_type=SourceType.upload, original_path="p",
    )
    doc_miss = Document(
        owner_user_id=user.id, name="Jasper 矿石图鉴",
        format="txt", size_bytes=1, sha256=str(uuid.uuid4()), status=DocumentStatus.indexed,
        source_type=SourceType.upload, original_path="p",
    )
    session.add_all([doc_hit, doc_miss])
    await session.flush()
    session.add_all(
        [
            Chunk(document_id=doc_hit.id, owner_user_id=user.id, content="无关正文",
                  embedding=[1.0, -1.0] * (settings.embedding_dim // 2)),
            Chunk(document_id=doc_miss.id, owner_user_id=user.id, content="无关正文",
                  embedding=[1.0, -1.0] * (settings.embedding_dim // 2)),
        ]
    )
    await session.commit()

    results = await hybrid_search(session, user.id, "我是jasonL")
    scores = {r.document_id: r.score for r in results}
    assert scores.get(doc_hit.id, 0) >= settings.retrieval_keyword_boost  # Jason L. 命中
    assert scores.get(doc_miss.id, 0) < settings.retrieval_keyword_boost  # Jasper 不误配
