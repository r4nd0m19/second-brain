#!/usr/bin/env python3
"""检索质量评测（范式专项工具，2026-10-03）：hit@k / MRR / 分数分布，多方案 A/B。

用法::

    cd server && .venv/bin/python tests/acceptance/retrieval_eval.py            # 全方案
    cd server && .venv/bin/python tests/acceptance/retrieval_eval.py --variant rrf

方案（不改生产代码，实验在脚本内实现）：
- current  现网：向量 top18 + 中文整句 ILIKE 加成 0.12
- vector   纯向量（boost=0）——衡量加成是否有效
- jieba    现网 + 查询端 jieba 分词（词元参与加成，替掉"整句成项"）
- rrf      双通道：向量 18 + 关键词召回 18（按匹配词数排序）→ RRF(k=60) 融合

指标：hit@6（期望文档出现在 top-6）/ MRR / 正确块余弦分（阈值标定用）/
兜底题 top1 分（正负样本分离度）。报告落盘 retrieval_eval_report.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select

warnings.filterwarnings("ignore", category=SyntaxWarning)  # jieba 老代码的转义告警

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.ingestion.embedding import get_embedding_provider  # noqa: E402
from app.models import Chunk, Document, User  # noqa: E402
from app.retrieval import search as search_mod  # noqa: E402
from app.retrieval.search import _keyword_condition, _tune_ann_scan  # noqa: E402

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
REPORT_FILE = Path(__file__).parent / "retrieval_eval_report.json"

TOP_K = settings.retrieval_top_k
POOL = TOP_K * 3
RRF_K = 60
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


async def _rerank_scores(query: str, docs: list[str]) -> list[float]:
    """硅基流动 rerank（cross-encoder）：对每条候选"真读一遍"再打分（0-1）。"""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.embedding_base_url}/rerank",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={
                "model": RERANK_MODEL,
                "query": query,
                "documents": docs,
                "top_n": len(docs),
            },
        )
        resp.raise_for_status()
    out = [0.0] * len(docs)
    for item in resp.json().get("results", []):
        out[int(item["index"])] = float(item["relevance_score"])
    return out

# 疑问/泛化词：jieba 分词后过滤（IR 通用停用词实践；避免"什么/怎么"这类词触发全库噪声加成）
_STOPWORDS = {
    "什么", "哪些", "哪个", "怎么", "如何", "为什么", "是否", "可以", "一个", "这个", "那个",
    "意思", "什么样", "怎么样", "大致", "大约", "多少", "推荐", "采用", "避免", "产生", "发生",
    "专门", "直接", "如果", "不行", "没有", "提到", "说的", "是否", "关于", "里怎么", "书里",
}


def jieba_terms(query: str, limit: int) -> list[str]:
    import jieba

    out: list[str] = []
    seen: set[str] = set()
    for w in jieba.lcut(query):
        w = w.strip()
        if len(w) < 2 or w.lower() in _STOPWORDS or w in seen:
            continue
        if not re.search(r"[一-鿿A-Za-z]", w):
            continue
        seen.add(w)
        out.append(w)
    return out[:limit]


@dataclass
class QRecord:
    qid: str
    category: str
    expected: str | None
    hit: bool = False
    rank: int | None = None
    best_score: float | None = None  # 期望文档块的方案分
    cosine: float | None = None  # 期望文档块的原始余弦（阈值标定）
    top1: float = 0.0  # 该题 top1 方案分（兜底题看分离度）
    results_n: int = 0


@dataclass
class VariantReport:
    name: str
    records: list[QRecord] = field(default_factory=list)

    def summary(self) -> dict:
        hits = [r for r in self.records if r.category == "hit"]
        fb = [r for r in self.records if r.category == "fallback"]
        mrr = 0.0
        for r in hits:
            if r.rank:
                mrr += 1.0 / r.rank
        cosines = [r.cosine for r in hits if r.cosine is not None]
        scores = [r.best_score for r in hits if r.best_score is not None]
        hit_top1 = [r.top1 for r in hits if r.hit]
        fb_top1 = [r.top1 for r in fb]
        return {
            "hit@6": f"{sum(1 for r in hits if r.hit)}/{len(hits)}",
            "MRR": round(mrr / max(len(hits), 1), 3),
            "正确块余弦均值": round(sum(cosines) / max(len(cosines), 1), 3) if cosines else None,
            "正确块分均值": round(sum(scores) / max(len(scores), 1), 3) if scores else None,
            "命中题 top1 最低": round(min(hit_top1), 3) if hit_top1 else None,
            "兜底题 top1 最高": round(max(fb_top1, default=0.0), 3),
            "分离间隔": (
                round(min(hit_top1) - max(fb_top1, default=0.0), 3) if hit_top1 else None
            ),
        }


class _CachedEmbed:
    """每题一次真实 embedding，跨方案复用（避免重复计费与抖动）。"""

    def __init__(self) -> None:
        self.v: list[float] | None = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert self.v is not None
        return [self.v for _ in texts]


async def _dense_rows(session, owner, vec, limit):
    distance = Chunk.embedding.cosine_distance(vec)
    return (
        await session.execute(
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.content,
                Chunk.heading_path,
                Chunk.page,
                Document.name,
                Document.source_type,
                distance.label("distance"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.owner_user_id == owner)
            .order_by(distance)
            .limit(limit)
        )
    ).all()


def _py_match(term: str, content: str, name: str) -> bool:
    """Python 侧近似 _keyword_condition（仅评测计数用）。"""
    if re.search(r"[一-鿿]", term):
        return term in content or term in name
    pat = re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.I)
    return bool(pat.search(content) or pat.search(name))


async def _keyword_rows(session, owner, terms):
    """关键词召回通道（rrf 方案）：匹配任一词元 → 按命中词数排序取 POOL 条。"""
    rows = (
        await session.execute(
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.content,
                Chunk.heading_path,
                Chunk.page,
                Document.name,
                Document.source_type,
            )
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.owner_user_id == owner, _any_term_condition(terms))
            .limit(300)
        )
    ).all()
    scored = []
    for row in rows:
        n = sum(1 for t in terms if _py_match(t, row.content or "", row.name or ""))
        if n:
            scored.append((n, row))
    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:POOL]]


def _any_term_condition(terms):
    from sqlalchemy import or_

    return or_(*[_keyword_condition(t) for t in terms])


def _rank_of_doc(rows, expected: str) -> tuple[int | None, object | None]:
    for i, row in enumerate(rows, start=1):
        if expected.lower() in (row.name or "").lower():
            return i, row
    return None, None


async def run_variants(session, owner, args) -> dict[str, VariantReport]:
    data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = [q for q in data["questions"] if q["category"] in ("hit", "fallback")]

    reports = {n: VariantReport(n) for n in args.variant}
    provider = get_embedding_provider()
    cached = _CachedEmbed()
    orig_terms = search_mod._terms
    orig_provider = search_mod.get_embedding_provider
    search_mod.get_embedding_provider = lambda: cached  # type: ignore[assignment]

    try:
        for q in questions:
            cached.v = (await provider.embed([q["question"]]))[0]
            expected = q.get("expected_document")

            if "current" in reports:
                rec = await _run_current(session, owner, q, expected)
                reports["current"].records.append(rec)
            if "vector" in reports:
                rec = await _run_vector(session, owner, q, expected)
                reports["vector"].records.append(rec)
            if "jieba" in reports:
                rec = await _run_jieba(session, owner, q, expected)
                reports["jieba"].records.append(rec)
            if "rrf" in reports:
                assert cached.v is not None
                rec = await _run_rrf(session, owner, q, expected, cached.v)
                reports["rrf"].records.append(rec)
            if "rerank" in reports:
                assert cached.v is not None
                rec = await _run_rerank(session, owner, q, expected, cached.v)
                reports["rerank"].records.append(rec)
            print(f"  ✓ {q['id']} {q['question'][:36]}…")
    finally:
        search_mod._terms = orig_terms  # type: ignore[assignment]
        search_mod.get_embedding_provider = orig_provider  # type: ignore[assignment]
    return reports


async def _run_current(session, owner, q, expected) -> QRecord:
    results = await search_mod.hybrid_search(session, owner, q["question"])
    return _score_record(q, expected, results)


async def _run_vector(session, owner, q, expected) -> QRecord:
    saved = settings.retrieval_keyword_boost
    settings.retrieval_keyword_boost = 0.0
    try:
        results = await search_mod.hybrid_search(session, owner, q["question"])
    finally:
        settings.retrieval_keyword_boost = saved
    return _score_record(q, expected, results)


async def _run_jieba(session, owner, q, expected) -> QRecord:
    search_mod._terms = jieba_terms  # type: ignore[assignment] — 签名兼容；run_variants 的 finally 统一还原
    results = await search_mod.hybrid_search(session, owner, q["question"])
    return _score_record(q, expected, results)


def _score_record(q, expected, results) -> QRecord:
    rec = QRecord(qid=q["id"], category=q["category"], expected=expected, results_n=len(results))
    rec.top1 = results[0].score if results else 0.0
    if expected:
        for i, r in enumerate(results, start=1):
            if expected.lower() in (r.document_name or "").lower():
                rec.hit = True
                rec.rank = i
                rec.best_score = r.score
                # 原始余弦 = 方案分 - 加成（jieba/current 才有加成；vector 无）
                rec.cosine = r.score  # current/jieba 后续修正
                break
    return rec


async def _run_rrf(session, owner, q, expected, vec) -> QRecord:
    """RRF(k=60) 融合：向量 18 条 + 关键词召回 18 条 → 取 top-K。"""
    terms = jieba_terms(q["question"], settings.retrieval_keyword_terms)
    await _tune_ann_scan(session, filtered=False)
    dense = await _dense_rows(session, owner, vec, POOL)
    kw = await _keyword_rows(session, owner, terms) if terms else []

    fused: dict = {}
    rows_by_id: dict = {}
    cosines: dict = {}
    for i, row in enumerate(dense, start=1):
        rows_by_id[row.id] = row
        cosines[row.id] = 1.0 - float(row.distance)
        fused[row.id] = fused.get(row.id, 0.0) + 1.0 / (RRF_K + i)
    for i, row in enumerate(kw, start=1):
        rows_by_id.setdefault(row.id, row)
        fused[row.id] = fused.get(row.id, 0.0) + 1.0 / (RRF_K + i)
    order = sorted(fused, key=lambda cid: -fused[cid])[:TOP_K]

    rec = QRecord(qid=q["id"], category=q["category"], expected=expected, results_n=len(order))
    rec.top1 = fused[order[0]] if order else 0.0
    if expected:
        for i, cid in enumerate(order, start=1):
            if expected.lower() in (rows_by_id[cid].name or "").lower():
                rec.hit = True
                rec.rank = i
                rec.best_score = fused[cid]
                rec.cosine = cosines.get(cid)  # 关键词-only 命中无余弦（None）
                break
    return rec


async def _run_rerank(session, owner, q, expected, vec) -> QRecord:
    """重排方案（A）：向量召回 18 → cross-encoder 真读打分 → 取 top-K。"""
    await _tune_ann_scan(session, filtered=False)
    dense = await _dense_rows(session, owner, vec, POOL)
    docs = [(row.content or "")[:2000] for row in dense]
    scores = await _rerank_scores(q["question"], docs) if docs else []
    order = sorted(range(len(dense)), key=lambda i: -scores[i])[:TOP_K]

    rec = QRecord(qid=q["id"], category=q["category"], expected=expected, results_n=len(order))
    rec.top1 = scores[order[0]] if order else 0.0
    if expected:
        for i, idx in enumerate(order, start=1):
            row = dense[idx]
            if expected.lower() in (row.name or "").lower():
                rec.hit = True
                rec.rank = i
                rec.best_score = scores[idx]
                rec.cosine = 1.0 - float(row.distance)
                break
    return rec


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", nargs="+", default=["current", "vector", "jieba", "rrf", "rerank"]
    )
    args = parser.parse_args()

    async with SessionLocal() as session:
        user = await session.scalar(select(User).limit(1))
        if user is None:
            raise SystemExit("库中无用户——先启动服务完成初始化")
        reports = await run_variants(session, user.id, args)

    print("\n== 检索质量对比（15 命中题 + 5 兜底题）==")
    out = {}
    for name, rep in reports.items():
        summary = rep.summary()
        out[name] = {"summary": summary, "records": [r.__dict__ for r in rep.records]}
        print(f"[{name:8}] {summary}")
        for r in rep.records:
            if r.category == "hit" and not r.hit:
                print(f"    ✗ 未命中 {r.qid}: {r.expected}（top1={r.top1:.3f}）")
    REPORT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
