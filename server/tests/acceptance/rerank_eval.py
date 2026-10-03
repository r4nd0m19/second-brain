#!/usr/bin/env python3
"""重排器对比评测（T076 / R34③）：同候选池下多款 cross-encoder 的命中指标 + 短语稳定性。

背景（R34③）：现行 bge-reranker-v2-m3 对同一文档的近义查询确定性复现 0.06 ↔ 0.92 的
分数抽奖（g05/g06 为已知样本）——本工具用**生产同款候选池**（向量 top18 + 关键词加成、
重排前；经 capture 补丁从 hybrid_search 内部取出）对全部候选重排器复评，隔离重排器变量。

指标：
- 命中集：hit@6 / MRR / 正确文档最高分（下限）
- 兜底集：top1 上限（越低越好）
- 分离间隔 = 正确分下限 − 兜底上限（R24 口径）
- 稳定性：同题近义改写下"正确文档最高分"的 min–max 跨度（抽奖的直接测量）

用法::

    cd server && .venv/bin/python tests/acceptance/rerank_eval.py
    cd server && .venv/bin/python tests/acceptance/rerank_eval.py --candidates BAAI/bge-reranker-v2-m3,Qwen/Qwen3-Reranker-8B

报告落盘 rerank_eval_report.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import warnings
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select

warnings.filterwarnings("ignore", category=SyntaxWarning)

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.retrieval import search as search_mod  # noqa: E402

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
REPORT_FILE = Path(__file__).parent / "rerank_eval_report.json"

DEFAULT_CANDIDATES = [
    "BAAI/bge-reranker-v2-m3",  # 现行（R24 选定）
    "Qwen/Qwen3-Reranker-8B",
    "Qwen/Qwen3-Reranker-4B",
    "Qwen/Qwen3-Reranker-0.6B",
]

TOP_K = 6

# 稳定性样本：同题近义改写（含 g05/g06 已知抖动样本；也覆盖一条常规命中题与一条游戏引擎题）
PARAPHRASES: dict[str, list[str]] = {
    "g05": [
        "环境映射（environment mapping）里，怎么找到某个表面点对应的贴图纹素？",
        "环境映射怎么查找表面点对应的纹素",
        "environment mapping texel lookup surface point",
        "环境映射 贴图纹素 查找",
        "环境贴图 反射向量 立方体贴图 采样",
        "球面映射 sphere mapping 纹素 查找",
        "How do you find the texel corresponding to a surface point in environment mapping?",
        "环境映射 表面点 对应 贴图纹素 查找",
    ],
    "g06": [
        "OpenAL 在书里被提到时的许可状况是怎样的？",
        "OpenAL 的许可协议是什么",
        "OpenAL license",
        "OpenAL license 授权 音频库",
        "OpenAL 音频库 许可协议",
        "What is the licensing status of OpenAL in the book?",
        "OpenAL 开源 商业许可",
        "OpenAL 许可 授权 license",
    ],
    "f01": [
        "书里把“大泥球”（Big Ball of Mud）这种架构描述成什么？给出的建议是什么？",
        "Big Ball of Mud 的定义与建议",
        "大泥球架构是什么",
        "big ball of mud architecture advice",
        "大泥球 定义 特征",
        "书里怎么描述大泥球",
    ],
    "g02": [
        "游戏循环（game loop）如果实现得不好，会产生什么副作用？",
        "game loop 实现不好的问题",
        "游戏循环 副作用",
        "game loop pitfalls",
        "游戏循环 掉帧 卡顿 原因",
    ],
}


async def rerank_scores(model: str, query: str, documents: list[str]) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.embedding_base_url}/rerank",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={"model": model, "query": query, "documents": documents, "top_n": len(documents)},
        )
        resp.raise_for_status()
    out = [0.0] * len(documents)
    for item in resp.json().get("results", []):
        out[int(item["index"])] = float(item["relevance_score"])
    return out


async def capture_pool(session, owner, query) -> list:
    """生产同款候选池（重排前）：打补丁从 hybrid_search 内部取出 ranked（≤ top_k×3）。"""
    captured: dict = {}

    async def _capture(q: str, items: list):
        captured["items"] = items
        return None  # 降级路径 → hybrid_search 正常返回（结果不用）

    orig = search_mod._apply_rerank
    search_mod._apply_rerank = _capture
    try:
        await search_mod.hybrid_search(session, owner, query)
    finally:
        search_mod._apply_rerank = orig
    return captured.get("items", [])


def score_pool(items: list, scores: list[float], expected: str | None, category: str) -> dict:
    ranked = sorted(zip(scores, items), key=lambda x: x[0], reverse=True)
    top1 = ranked[0][0] if ranked else 0.0
    rec = {"top1": top1, "hit": False, "rank": None, "expected_best": None}
    if expected:
        for i, (score, item) in enumerate(ranked, start=1):
            if expected.lower() in (item.document_name or "").lower():
                rec["hit"] = i <= TOP_K
                rec["rank"] = i
                rec["expected_best"] = score
                break
    return rec


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default=",".join(DEFAULT_CANDIDATES))
    args = parser.parse_args()
    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]

    data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = [q for q in data["questions"] if q["category"] in ("hit", "fallback")]

    async with SessionLocal() as session:
        owner = (await session.scalar(select(User).limit(1))).id
        report: dict = {"candidates": candidates, "metrics": {}, "stability": {}}

        # ---- 第一遍：逐题取生产同款候选池 ----
        pools: dict[str, tuple[list, str | None, str, str]] = {}
        for q in questions:
            items = await capture_pool(session, owner, q["question"])
            pools[q["id"]] = (items, q.get("expected_document"), q["category"], q["question"])
            print(f"  pool {q['id']}: {len(items)} 条", flush=True)

        # ---- 每候选：对同一池复评 ----
        for model in candidates:
            per_q: dict[str, dict] = {}
            ok = True
            durs: list[float] = []
            for qid, (items, expected, category, qtext) in pools.items():
                try:
                    t0 = time.perf_counter()
                    scores = await rerank_scores(
                        model, qtext, [it.content[:2000] for it in items]
                    )
                    durs.append(time.perf_counter() - t0)
                except Exception as e:  # noqa: BLE001
                    per_q[qid] = {"error": str(e)[:120]}
                    ok = False
                    continue
                per_q[qid] = score_pool(items, scores, expected, category)
            if not ok and all("error" in v for v in per_q.values()):
                report["metrics"][model] = {"error": "all failed", "sample": next(iter(per_q.values()))}
                print(f"== {model}: 全部失败 {next(iter(per_q.values()))}")
                continue

            hits = [v for qid, v in per_q.items() if pools[qid][2] == "hit" and "error" not in v]
            falls = [v for qid, v in per_q.items() if pools[qid][2] == "fallback" and "error" not in v]
            hit_n = sum(1 for v in hits if v["hit"])
            ranks = [v["rank"] for v in hits if v.get("rank")]
            mrr = statistics.mean(1.0 / r for r in ranks) if ranks else 0.0
            exp_min = min((v["expected_best"] for v in hits if v["expected_best"] is not None), default=None)
            fall_max = max((v["top1"] for v in falls), default=0.0)
            report["metrics"][model] = {
                "hit@6": f"{hit_n}/{len(hits)}",
                "MRR": round(mrr, 3),
                "correct_min": round(exp_min, 3) if exp_min is not None else None,
                "fallback_max": round(fall_max, 3),
                "separation": round(exp_min - fall_max, 3) if exp_min is not None else None,
                "latency_avg_s": round(statistics.mean(durs), 3) if durs else None,
                "records": per_q,
            }
            print(
                f"== {model}: hit@6={hit_n}/{len(hits)} MRR={mrr:.3f} "
                f"正确分下限={exp_min if exp_min is None else round(exp_min, 3)} "
                f"兜底上限={round(fall_max, 3)} 分离={None if exp_min is None else round(exp_min - fall_max, 3)} "
                f"延迟均值={round(statistics.mean(durs), 3) if durs else '-'}s"
            )

        # ---- 稳定性：近义改写下的"正确文档最高分"跨度 ----
        for model in candidates:
            spans = {}
            for qid, paraphrases in PARAPHRASES.items():
                expected = next((q.get("expected_document") for q in questions if q["id"] == qid), None)
                vals = []
                for p in paraphrases:
                    items = await capture_pool(session, owner, p)
                    try:
                        scores = await rerank_scores(model, p, [it.content[:2000] for it in items])
                    except Exception:  # noqa: BLE001
                        continue
                    rec = score_pool(items, scores, expected, "hit")
                    if rec["expected_best"] is not None:
                        vals.append(round(rec["expected_best"], 3))
                if vals:
                    spans[qid] = {
                        "min": min(vals), "max": max(vals),
                        "span": round(max(vals) - min(vals), 3),
                        "values": vals,
                    }
            report["stability"][model] = spans
            print(f"== 稳定性 {model}:")
            for qid, s in spans.items():
                print(f"   {qid}: 跨度 {s['span']}（{s['min']}–{s['max']}）")

    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
