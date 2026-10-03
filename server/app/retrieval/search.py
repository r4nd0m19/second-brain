"""混合检索（T019 + T033）：pgvector 向量检索 + 关键词加成；接口可替换（constitution VII）。

中文关键词检索（T033）：pg_trgm GIN 索引加速 ILIKE 子串匹配（zhparser 不在官方镜像，见 research R9）；
混合权重（加成值/拆词上限）经 settings 可配置。

阈值语义（spec FR-007）：
- score ≥ hit_threshold          → 命中：基于库内容作答（kb），带出处
- weak_threshold ≤ score < hit   → 弱相关：兜底作答 + "库中可能相关"提示
- score < weak_threshold         → 视为库外：纯兜底
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.costing import add_retrieval
from app.ingestion.embedding import get_embedding_provider
from app.models import Chunk, Document, SourceType

QUOTE_MAX = 300  # 引用片段长度上限（data-model 约定）

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿]")


def _ascii_word_pattern(term: str) -> str:
    """ASCII 词项 → 词边界 + 词内弹性分隔（人名连写/分写互通：jasonL ↔ "Jason L." / "jason-l"）。

    2026-10-02 实测：用户「我是jasonL」无法命中资料中的 "Jason L."（空格/点分隔）。
    词边界（防 face↔interface）保留，仅在词内字符之间允许分隔符；仅作用于候选块，无性能顾虑。
    """
    chars = [ch for ch in term if ch.isalnum()]
    glued = r"[\s.\-–—_]*".join(re.escape(ch) for ch in chars)
    return rf"\m{glued}\M"


def _keyword_condition(term: str):
    """关键词匹配条件：中文用子串（ILIKE）；ASCII 词用词边界+弹性分隔（2026-10-02）。"""
    if _CJK_RE.search(term):
        return or_(Chunk.content.ilike(f"%{term}%"), Document.name.ilike(f"%{term}%"))
    pattern = _ascii_word_pattern(term)  # ARE 词边界；re.escape 防正则元字符
    return or_(Chunk.content.op("~*")(pattern), Document.name.op("~*")(pattern))


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
    # 对话回写来源：所属会话（前端「回到原对话」跳转用）
    conversation_id: uuid.UUID | None = None

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
        if self.conversation_id is not None:  # 对话回写来源：回到原对话
            citation["conversation_id"] = str(self.conversation_id)
        return citation


_ASCII_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}")
_WORD_CHAR_RE = re.compile(r"[一-鿿A-Za-z]")  # 词项须含中文或字母（纯数字不参与关键词加成）


def _terms(query: str, limit: int) -> list[str]:
    parts = re.split(r"[\s，。？！,.?!;；:：、（）()【】\[\]]+", query)
    # 纯数字/符号词项剔除（2026-10-02 实测："37" 词界命中 SVG 坐标 "37.8399" 造成假性加成）
    terms = [p for p in parts if len(p) >= 2 and _WORD_CHAR_RE.search(p)]
    # 中英混排：英文词单独成项（实测 2026-10-02：'…在upwork上面的资料' 整句成项，
    # 导致 "upwork" 未参与关键词匹配；'Next.js' 这类技术名词同理）
    seen = {t.lower() for t in terms}
    for ascii_term in _ASCII_TERM_RE.findall(query):
        if ascii_term.lower() not in seen:
            terms.append(ascii_term)
            seen.add(ascii_term.lower())
    return terms[:limit]


_pgvector_iterative: bool | None = None


async def _tune_ann_scan(session: AsyncSession, *, filtered: bool) -> None:
    """pgvector ≥0.8：统一提升 ef_search（召回余量）+ 带过滤时启用迭代扫描（R5）。

    2026-10-02 实测：HNSW 在高删改量下召回退化（默认 ef_search=40 时曾丢失精确最近邻，
    升高后恢复；彻底恢复需 REINDEX，见 001 research R16）。ef_search 取可配置值。
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
        await session.execute(
            text(f"SET LOCAL hnsw.ef_search = {int(settings.retrieval_ef_search)}")
        )
        if filtered:
            await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))


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
    await _tune_ann_scan(session, filtered=bool(time_conditions))

    distance = Chunk.embedding.cosine_distance(query_vec)
    vector_rows = (
        await session.execute(
            select(
                Chunk,
                Document.name,
                Document.source_type,
                Document.source_url,
                Document.last_captured_at,
                Document.conversation_id,
                distance.label("distance"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.owner_user_id == owner_user_id, *time_conditions)
            .order_by(distance)
            .limit(top_k * 3)  # 候选池 ≈3×结果数（融合惯例，R15）
        )
    ).all()

    found: dict[uuid.UUID, RetrievedChunk] = {}
    scores: dict[uuid.UUID, float] = {}
    for chunk, doc_name, doc_source, doc_url, doc_captured, doc_conv, dist in vector_rows:
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
            conversation_id=doc_conv,
        )
        scores[chunk.id] = 1.0 - float(dist)  # 余弦相似度

    terms = _terms(query, settings.retrieval_keyword_terms)
    if terms and found:
        # 关键词加成**仅作用于向量候选**（融合加权，R15）：不独立召回——
        # 此前实现对"以文档名命中"的大文档只随机加成 top_k 个子集（无排序 + LIMIT），
        # 同等相关块时有时无；纯关键词块得分 ≤boost 远低于弱阈值，独立召回本就无实效。
        keyword_hit_ids = await session.scalars(
            select(Chunk.id)
            .join(Document, Chunk.document_id == Document.id)
            .where(
                Chunk.id.in_(list(found.keys())),
                # 正文或**网页标题（document.name）**命中均计入
                # （实测 2026-10-02：SPA 页正文可能只有导航，标题才是最佳信号）
                or_(*[_keyword_condition(t) for t in terms]),
            )
        )
        for chunk_id in keyword_hit_ids:  # 关键词加成
            scores[chunk_id] = scores.get(chunk_id, 0.0) + settings.retrieval_keyword_boost

    ranked = sorted(found.values(), key=lambda r: scores[r.chunk_id], reverse=True)
    for item in ranked:
        item.score = scores[item.chunk_id]

    # 二段式重排（R24/A 方案）：cross-encoder 对候选池"真读复评"，重排分即最终分；
    # 失败/关闭时静默降级为余弦+加成（constitution VI）。
    # 注：评分尺度随来源切换——重排成功为重排分（0-1，0.60/0.50 阈值实测落于分离间隔内），
    # 降级时为余弦+加成（旧口径）；两种尺度的阈值语义见 research R24。
    reranked = await _apply_rerank(query, ranked)
    if reranked is not None:
        return reranked[:top_k]
    return ranked[:top_k]


async def _apply_rerank(query: str, items: list[RetrievedChunk]) -> list[RetrievedChunk] | None:
    """二段式重排（R24）：重排分替换 score 并重排序；不可用/失败返回 None（调用方降级）。"""
    if not settings.rerank_enabled or not settings.embedding_api_key or not items:
        return None
    try:
        scores = await _rerank_api(query, [it.content[:2000] for it in items])
        for i, item in enumerate(items):
            item.score = scores[i]
        return sorted(items, key=lambda r: r.score, reverse=True)
    except Exception:  # noqa: BLE001 — 重排失败静默降级，不阻塞问答
        logger.warning("rerank failed; degrading to cosine+boost", exc_info=True)
        return None


async def _rerank_api(query: str, documents: list[str]) -> list[float]:
    """硅基流动 rerank（cross-encoder，与 embedding 同源 key）；返回与输入等长的分数表。"""
    async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
        resp = await client.post(
            f"{settings.embedding_base_url}/rerank",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={
                "model": settings.rerank_model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
            },
        )
        resp.raise_for_status()
    data = resp.json()
    out = [0.0] * len(documents)
    for item in data.get("results", []):
        out[int(item["index"])] = float(item["relevance_score"])
    # 全成本（T079）：重排按 tokens 计价（Qwen3-Reranker-4B，usage 在 meta.tokens）
    rerank_tokens = int(((data.get("meta") or {}).get("tokens") or {}).get("input_tokens", 0))
    if rerank_tokens:
        add_retrieval(rerank_tokens / 1_000_000 * settings.price_rerank_per_million)
    return out


async def rerank_texts(query: str, documents: list[str]) -> list[float]:
    """对外暴露的重排打分（联网结果过滤等复用，R37/T081）；费用经 add_retrieval 计入本回合。"""
    return await _rerank_api(query, documents)
