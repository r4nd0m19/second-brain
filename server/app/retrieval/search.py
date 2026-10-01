"""混合检索（T019）：pgvector 向量检索 + 关键词加成；接口可替换（constitution VII）。

v1 说明：中文全文检索（zhparser/pg_trgm）在 T033 接入；当前为"向量为主 + ILIKE 关键词加成"。

阈值语义（spec FR-007）：
- score ≥ hit_threshold          → 命中：基于库内容作答（kb），带出处
- weak_threshold ≤ score < hit   → 弱相关：兜底作答 + "库中可能相关"提示
- score < weak_threshold         → 视为库外：纯兜底
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
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

    def to_citation(self) -> dict:
        """出处三要素（FR-006）：资料名 + 位置 + 原文引用片段。"""
        return {
            "document_id": str(self.document_id),
            "chunk_id": str(self.chunk_id),
            "document_name": self.document_name,
            "heading_path": self.heading_path,
            "page": self.page,
            "quote": self.content[:QUOTE_MAX],
        }


def _terms(query: str) -> list[str]:
    parts = re.split(r"[\s，。？！,.?!;；:：、（）()【】\[\]]+", query)
    return [p for p in parts if len(p) >= 2][:4]


async def hybrid_search(
    session: AsyncSession, owner_user_id: uuid.UUID, query: str
) -> list[RetrievedChunk]:
    provider = get_embedding_provider()
    query_vec = (await provider.embed([query]))[0]
    top_k = settings.retrieval_top_k

    distance = Chunk.embedding.cosine_distance(query_vec)
    vector_rows = (
        await session.execute(
            select(Chunk, Document.name, Document.source_type, distance.label("distance"))
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.owner_user_id == owner_user_id)
            .order_by(distance)
            .limit(top_k * 2)
        )
    ).all()

    found: dict[uuid.UUID, RetrievedChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    for chunk, doc_name, doc_source, dist in vector_rows:
        found[chunk.id] = RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=doc_name,
            source_type=doc_source,
            content=chunk.content,
            heading_path=chunk.heading_path,
            page=chunk.page,
            score=0.0,
        )
        scores[chunk.id] = 1.0 - float(dist)  # 余弦相似度

    terms = _terms(query)
    if terms:
        keyword_rows = (
            await session.execute(
                select(Chunk, Document.name, Document.source_type)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Chunk.owner_user_id == owner_user_id,
                    or_(*[Chunk.content.ilike(f"%{t}%") for t in terms]),
                )
                .limit(top_k)
            )
        ).all()
        for chunk, doc_name, doc_source in keyword_rows:  # 关键词加成
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 0.05
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
                )

    ranked = sorted(found.values(), key=lambda r: scores[r.chunk_id], reverse=True)[:top_k]
    for item in ranked:
        item.score = scores[item.chunk_id]
    return ranked
