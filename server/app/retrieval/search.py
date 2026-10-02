"""混合检索（T019 + T033）：pgvector 向量检索 + 关键词加成；接口可替换（constitution VII）。

中文关键词检索（T033）：pg_trgm GIN 索引加速 ILIKE 子串匹配（zhparser 不在官方镜像，见 research R9）；
混合权重（加成值/拆词上限）经 settings 可配置。

阈值语义（spec FR-007）：
- score ≥ hit_threshold          → 命中：基于库内容作答（kb），带出处
- weak_threshold ≤ score < hit   → 弱相关：兜底作答 + "库中可能相关"提示
- score < weak_threshold         → 视为库外：纯兜底
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion.embedding import get_embedding_provider
from app.models import Chunk, Document, SourceType

QUOTE_MAX = 300  # 引用片段长度上限（data-model 约定）


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    source_type: SourceType
    content: str
    heading_path: str | None
    page: int | None
    score: float
    # 浏览器来源（F2）：出处附链接与浏览时间（FR-003）
    source_url: str | None = None
    last_captured_at: datetime | None = None

    def to_citation(self) -> dict:
        """出处三要素（FR-006）：资料名 + 位置 + 原文引用片段；网页来源附加链接与时间。"""
        citation = {
            "document_id": str(self.document_id),
            "chunk_id": str(self.chunk_id),
            "document_name": self.document_name,
            "heading_path": self.heading_path,
            "page": self.page,
            "quote": self.content[:QUOTE_MAX],
        }
        if self.source_type is SourceType.browser:
            citation["source_url"] = self.source_url
            citation["last_captured_at"] = (
                self.last_captured_at.isoformat() if self.last_captured_at else None
            )
        return citation


_ASCII_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}")


def _terms(query: str, limit: int) -> list[str]:
    parts = re.split(r"[\s，。？！,.?!;；:：、（）()【】\[\]]+", query)
    terms = [p for p in parts if len(p) >= 2]
    # 中英混排：英文词单独成项（实测 2026-10-02：'…在upwork上面的资料' 整句成项，
    # 导致 "upwork" 未参与关键词匹配；'Next.js' 这类技术名词同理）
    seen = {t.lower() for t in terms}
    for ascii_term in _ASCII_TERM_RE.findall(query):
        if ascii_term.lower() not in seen:
            terms.append(ascii_term)
            seen.add(ascii_term.lower())
    return terms[:limit]


_pgvector_iterative: bool | None = None


async def _enable_iterative_scan(session: AsyncSession) -> None:
    """pgvector ≥0.8 时启用迭代扫描（过滤后取 top-k 防 overfiltering；R5）。

    版本探测结果进程内缓存；老版本/无扩展时静默跳过（退化为普通过滤）。
    """
    global _pgvector_iterative
    if _pgvector_iterative is None:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        try:
            _pgvector_iterative = bool(version) and tuple(
                int(part) for part in str(version).split(".")[:2]
            ) >= (0, 8)
        except ValueError:
            _pgvector_iterative = False
    if _pgvector_iterative:
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        await session.execute(text("SET LOCAL hnsw.ef_search = 100"))


def _time_conditions(
    captured_after: datetime | None, captured_before: datetime | None
) -> list:
    """时间过滤条件（作用于 documents.last_captured_at；F2 US3）。仅浏览器来源有时间列。"""
    conditions = []
    if captured_after is not None:
        conditions.append(Document.last_captured_at >= captured_after)
    if captured_before is not None:
        conditions.append(Document.last_captured_at < captured_before)
    return conditions


async def hybrid_search(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    query: str,
    captured_after: datetime | None = None,
    captured_before: datetime | None = None,
) -> list[RetrievedChunk]:
    provider = get_embedding_provider()
    query_vec = (await provider.embed([query]))[0]
    top_k = settings.retrieval_top_k
    time_conditions = _time_conditions(captured_after, captured_before)
    if time_conditions:
        await _enable_iterative_scan(session)

    distance = Chunk.embedding.cosine_distance(query_vec)
    vector_rows = (
        await session.execute(
            select(
                Chunk,
                Document.name,
                Document.source_type,
                Document.source_url,
                Document.last_captured_at,
                distance.label("distance"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.owner_user_id == owner_user_id, *time_conditions)
            .order_by(distance)
            .limit(top_k * 2)
        )
    ).all()

    found: dict[uuid.UUID, RetrievedChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    for chunk, doc_name, doc_source, doc_url, doc_captured, dist in vector_rows:
        found[chunk.id] = RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=doc_name,
            source_type=doc_source,
            content=chunk.content,
            heading_path=chunk.heading_path,
            page=chunk.page,
            score=0.0,
            source_url=doc_url,
            last_captured_at=doc_captured,
        )
        scores[chunk.id] = 1.0 - float(dist)  # 余弦相似度

    terms = _terms(query, settings.retrieval_keyword_terms)
    if terms:
        keyword_rows = (
            await session.execute(
                select(Chunk, Document.name, Document.source_type, Document.source_url, Document.last_captured_at)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Chunk.owner_user_id == owner_user_id,
                    # 正文或**网页标题（document.name）**命中均计入
                    # （实测 2026-10-02：SPA 页正文可能只有导航，标题才是最佳信号）
                    or_(
                        *[
                            or_(Chunk.content.ilike(f"%{t}%"), Document.name.ilike(f"%{t}%"))
                            for t in terms
                        ]
                    ),
                    *time_conditions,
                )
                .limit(top_k)
            )
        ).all()
        for chunk, doc_name, doc_source, doc_url, doc_captured in keyword_rows:  # 关键词加成
            scores[chunk.id] = scores.get(chunk.id, 0.0) + settings.retrieval_keyword_boost
            if chunk.id not in found:
                found[chunk.id] = RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=doc_name,
                    source_type=doc_source,
                    content=chunk.content,
                    heading_path=chunk.heading_path,
                    page=chunk.page,
                    score=0.0,
                    source_url=doc_url,
                    last_captured_at=doc_captured,
                )

    ranked = sorted(found.values(), key=lambda r: scores[r.chunk_id], reverse=True)[:top_k]
    for item in ranked:
        item.score = scores[item.chunk_id]
    return ranked
