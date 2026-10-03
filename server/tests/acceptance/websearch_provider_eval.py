#!/usr/bin/env python3
"""联网搜索源对比评测（T086/R40）：SearXNG（自建）vs DeepSeek 服务端搜索（官方）。

同题对照四个量：延迟 / 结果数 / top 相关性（cross-encoder 复评分，与生产闸门同口径，可用时）/
成本（DeepSeek 为 token 制，经成本聚合器实测；SearXNG 恒 0）。

用法::

    cd server && .venv/bin/python tests/acceptance/websearch_provider_eval.py
    cd server && .venv/bin/python tests/acceptance/websearch_provider_eval.py --providers searxng

报告落盘 websearch_provider_eval_report.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings
from app.costing import current, start_turn
from app.websearch.client import WebSearchError

REPORT_FILE = Path(__file__).parent / "websearch_provider_eval_report.json"

QUERIES = [
    "Upwork 2026 年需求量最大的软件项目类型",
    "FastAPI 后台任务 最佳实践",
    "httpx 连接池配置注意事项",
    "美联储 最新 利率决议",
]


def build_client(provider: str):
    if provider == "searxng":
        from app.websearch.searxng import SearXNGClient

        return SearXNGClient(
            base_url=settings.searxng_base_url, timeout=settings.searxng_timeout_s
        )
    if provider == "deepseek":
        from app.websearch.deepseek import DeepSeekWebSearch

        return DeepSeekWebSearch(
            api_key=settings.llm_api_key,
            base_url=settings.deepseek_search_base_url
            or f"{settings.llm_base_url.rstrip('/')}/anthropic",
            model=settings.deepseek_search_model,
            timeout=settings.deepseek_search_timeout_s,
        )
    raise ValueError(f"未知 provider: {provider}")


async def top_score(question: str, results) -> float | None:
    """cross-encoder 对「标题+摘要」按问题复评的最高分（生产闸门口径；不可用 → None）。"""
    if not settings.rerank_enabled or not settings.embedding_api_key or not results:
        return None
    from app.retrieval.search import rerank_texts

    docs = [f"{r.title}\n{(r.snippet or '')[:400]}" for r in results]
    try:
        scores = await rerank_texts(question, docs)
    except Exception:  # noqa: BLE001 — 评测辅助，失败不阻塞
        return None
    return max(scores) if scores else None


async def run_provider(provider: str, queries: list[str]) -> list[dict]:
    client = build_client(provider)
    rows: list[dict] = []
    for query in queries:
        start_turn()
        t0 = time.monotonic()
        error = None
        results = []
        try:
            results = await client.search(query, settings.web_search_max_results)
        except WebSearchError as exc:
            error = str(exc)[:200]
        latency = time.monotonic() - t0
        turn = current()
        score = await top_score(query, results)
        rows.append(
            {
                "provider": provider,
                "query": query,
                "latency_s": round(latency, 2),
                "count": len(results),
                "cost_cny": round(turn.web_cny, 6) if turn else 0.0,
                "top_score": round(score, 3) if score is not None else None,
                "error": error,
                "top": [
                    {"title": r.title[:90], "url": r.url, "site": r.site_name}
                    for r in results[:5]
                ],
            }
        )
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default="searxng,deepseek")
    args = parser.parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    all_rows: list[dict] = []
    for provider in providers:
        rows = await run_provider(provider, QUERIES)
        all_rows.extend(rows)
        print(f"\n=== {provider} ===")
        for row in rows:
            score = row["top_score"] if row["top_score"] is not None else "-"
            line = (
                f"{row['latency_s']:>6.2f}s  n={row['count']:<3} "
                f"¥{row['cost_cny']:.4f}  score={score}  {row['query'][:36]}"
            )
            if row["error"]:
                line += f"  ERR:{row['error'][:60]}"
            print(line)
            for item in row["top"][:3]:
                print(f"        - {item['title'][:64]} | {item['url'][:84]}")

    REPORT_FILE.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2))
    print(f"\n报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
