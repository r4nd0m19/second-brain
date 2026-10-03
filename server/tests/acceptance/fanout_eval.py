#!/usr/bin/env python3
"""扇出假强命中专项评测（T077 / R34④）：量化 `_expanded_search`（低置信多查询扇出）的
收益（命中集抬升）与代价（兜底集被变体推过强线），并在**采集数据**上模拟三个候选缓解。

规则与生产一致：base 检索（Qwen3 重排）不强（<0.60）才扇出；变体各自 hybrid_search、
按块合并取最高分、窗口 2×top_k；强线 = retrieval_hit_threshold。变体原文随报告落盘（可审计）。

用法::

    cd server && .venv/bin/python tests/acceptance/fanout_eval.py                 # 20 题 × 3 轮
    cd server && .venv/bin/python tests/acceptance/fanout_eval.py --rounds 2 --ids b01,b02

报告落盘 fanout_eval_report.json。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import warnings
from pathlib import Path

import yaml
from sqlalchemy import select

warnings.filterwarnings("ignore", category=SyntaxWarning)

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.retrieval import expand_queries, hybrid_search  # noqa: E402
from app.retrieval.search import _terms  # noqa: E402

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
REPORT_FILE = Path(__file__).parent / "fanout_eval_report.json"

STRONG = settings.retrieval_hit_threshold
WINDOW = settings.retrieval_top_k * 2


def _term_match(term: str, content: str, name: str) -> bool:
    if re.search(r"[一-鿿]", term):
        return term in content or term in name
    pat = re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.I)
    return bool(pat.search(content) or pat.search(name))


def _corroborated(question: str, hit) -> bool:
    """变体来源分数是否带**原问题**词项佐证（候选①判据；与生产 _terms 同口径）。"""
    terms = _terms(question, settings.retrieval_keyword_terms)
    return any(_term_match(t, hit.content or "", hit.document_name or "") for t in terms)


async def _one_round(session, owner, question, base_hits) -> dict:
    """单轮扇出：expand → 变体检索 → 按块合并取最高分（与 _expanded_search 同规则）+ 溯源。"""
    variants = await expand_queries(question)
    best: dict = {h.chunk_id: (h, "base") for h in base_hits}
    for v in variants:
        for h in await hybrid_search(session, owner, v):
            cur = best.get(h.chunk_id)
            if cur is None or h.score > cur[0].score:
                best[h.chunk_id] = (h, v)
    merged = sorted(best.values(), key=lambda it: it[0].score, reverse=True)[:WINDOW]
    return {"variants": variants, "merged": merged}


def _round_record(question: str, expected: str | None, rr: dict) -> dict:
    merged = rr["merged"]
    top, top_src = merged[0] if merged else (None, None)
    rec = {
        "variants": rr["variants"],
        "top1": round(top.score, 3) if top else 0.0,
        "top1_doc": top.document_name if top else None,
        "top1_source": top_src if top else None,  # "base" 或命中的变体原文
        "strong": bool(top and top.score >= STRONG),
        "top1_corroborated": _corroborated(question, top) if top else None,
        "strong_hits": [
            {"doc": h.document_name, "score": round(h.score, 3), "source": s}
            for h, s in merged
            if h.score >= STRONG
        ][:5],
    }
    if expected:
        rec["expected_rank"] = None
        rec["expected_score"] = None
        rec["expected_source"] = None
        rec["expected_corroborated"] = None
        for i, (h, s) in enumerate(merged, start=1):
            if expected.lower() in (h.document_name or "").lower():
                rec["expected_rank"] = i
                rec["expected_score"] = round(h.score, 3)
                rec["expected_source"] = s
                rec["expected_corroborated"] = _corroborated(question, h)
                break
    return rec


async def run(session, owner, rounds: int, ids: list[str] | None) -> list[dict]:
    data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = [q for q in data["questions"] if q["category"] in ("hit", "fallback")]
    if ids:
        questions = [q for q in questions if q["id"] in ids]

    records: list[dict] = []
    for q in questions:
        expected = q.get("expected_document")
        t0 = time.monotonic()
        base_hits = await hybrid_search(session, owner, q["question"])
        base_top = base_hits[0].score if base_hits else 0.0
        row = {
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "expected": expected,
            "base_top1": round(base_top, 3),
            "base_doc": base_hits[0].document_name if base_hits else None,
            "base_strong": base_top >= STRONG,
            "base_expected_score": next(
                (
                    round(h.score, 3)
                    for h in base_hits
                    if expected and expected.lower() in (h.document_name or "").lower()
                ),
                None,
            ),
            "fanned": base_top < STRONG,  # 生产路径：仅低置信时扇出
            "rounds": [],
        }
        if row["fanned"]:
            for _ in range(rounds):
                rr = await _one_round(session, owner, q["question"], base_hits)
                row["rounds"].append(_round_record(q["question"], expected, rr))
        row["elapsed_s"] = round(time.monotonic() - t0, 1)
        records.append(row)
        tag = "扇出3轮" if row["fanned"] else "基强跳过"
        print(f"  ✓ {q['id']:4} [{tag}] base_top1={row['base_top1']:.3f} {row['elapsed_s']}s")
    return records


def analyze(records: list[dict]) -> dict:
    """基线统计 + 三候选缓解模拟（全部在采集数据上重算，不改生产代码）。"""
    fb = [r for r in records if r["category"] == "fallback" and r["fanned"]]
    hits = [r for r in records if r["category"] == "hit"]

    def fb_events():
        for r in fb:
            for i, rd in enumerate(r["rounds"], start=1):
                yield r, i, rd

    baseline_false = [
        {
            "id": r["id"],
            "round": i,
            "top1": rd["top1"],
            "doc": rd["top1_doc"],
            "source": (rd["top1_source"] or "")[:40],
            "corroborated": rd["top1_corroborated"],
        }
        for r, i, rd in fb_events()
        if rd["strong"]
    ]

    rescues, mis_rescues = [], []
    for r in hits:
        if not r["fanned"]:
            continue
        got = any((rd.get("expected_score") or 0) >= STRONG for rd in r["rounds"])
        wrong = any(
            rd["strong"] and (rd.get("expected_score") or 0) < STRONG for rd in r["rounds"]
        )
        if got:
            rescues.append({"id": r["id"], "base_top1": r["base_top1"]})
        elif wrong:
            mis_rescues.append({"id": r["id"], "base_top1": r["base_top1"]})

    # 候选③ 触发收紧：仅当 base_top1 ≥ X 才扇出（低于则假强不再产生、救回也放弃）
    trigger_sim = {}
    for x in (0.0, 0.30, 0.45, 0.50):
        false_left = sum(1 for r, _, rd in fb_events() if rd["strong"] and r["base_top1"] >= x)
        kept = [
            s for s in rescues if next(r for r in hits if r["id"] == s["id"])["base_top1"] >= x
        ]
        trigger_sim[f"{x:.2f}"] = {
            "兜底假强剩余(轮次)": false_left,
            "命中救回保留": f"{len(kept)}/{len(rescues)}",
        }

    # 候选② 变体惩罚 δ：变体来源分值 −δ 后再判强线
    penalty_sim = {}
    for d in (0.0, 0.03, 0.05, 0.08, 0.10):
        false_left = 0
        for _, _, rd in fb_events():
            eff = rd["top1"] - d if rd["top1_source"] != "base" else rd["top1"]
            false_left += eff >= STRONG
        kept = 0
        for s in rescues:
            r = next(r for r in hits if r["id"] == s["id"])
            ok = False
            for rd in r["rounds"]:
                sc = rd.get("expected_score") or 0
                src = rd.get("expected_source")
                eff = sc - d if (src and src != "base") else sc
                if eff >= STRONG:
                    ok = True
                    break
            kept += ok
        penalty_sim[f"{d:.2f}"] = {
            "兜底假强剩余(轮次)": false_left,
            "命中救回保留": f"{kept}/{len(rescues)}",
        }

    # 候选① 佐证要求：变体来源强命中须带原问题词项（否则视同不强）
    false_left_1 = sum(
        1
        for _, _, rd in fb_events()
        if rd["strong"] and (rd["top1_source"] == "base" or rd["top1_corroborated"])
    )
    kept_1 = 0
    for s in rescues:
        r = next(r for r in hits if r["id"] == s["id"])
        for rd in r["rounds"]:
            sc = rd.get("expected_score") or 0
            if sc < STRONG:
                continue
            src = rd.get("expected_source")
            if src == "base" or rd.get("expected_corroborated"):
                kept_1 += 1
                break

    return {
        "基线（现生产·扇出开）": {
            "兜底假强明细": baseline_false,
            "兜底假强(轮次合计)": len(baseline_false),
            "兜底题数(扇出触发)": len(fb),
            "命中集救回": rescues,
            "命中集强错文档": mis_rescues,
        },
        "候选③ 触发收紧(仅 base≥X 扇出)": trigger_sim,
        "候选② 变体惩罚(变体来源 −δ)": penalty_sim,
        "候选① 佐证要求(原问题词项)": {
            "兜底假强剩余(轮次)": false_left_1,
            "命中救回保留": f"{kept_1}/{len(rescues)}",
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--ids", default="")
    args = parser.parse_args()
    ids = [s.strip() for s in args.ids.split(",") if s.strip()] or None

    async with SessionLocal() as session:
        user = await session.scalar(select(User).limit(1))
        if user is None:
            raise SystemExit("库中无用户——先启动服务完成初始化")
        print(f"== 扇出评测（{args.rounds} 轮）==")
        records = await run(session, user.id, args.rounds, ids)

    analysis = analyze(records)
    report = {"config": {"rounds": args.rounds, "strong": STRONG, "window": WINDOW},
              "records": records, "analysis": analysis}
    REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 分析 ==")
    base = analysis["基线（现生产·扇出开）"]
    print(f"兜底假强（轮次合计）: {base['兜底假强(轮次合计)']} / {len(records)} 题 {args.rounds} 轮")
    for e in base["兜底假强明细"]:
        print(f"    ! {e['id']} r{e['round']} top1={e['top1']} 《{e['doc']}》 ← {e['source']}…")
    print(f"命中集救回: {base['命中集救回']}")
    print(f"命中集强错文档: {base['命中集强错文档']}")
    print(f"候选③ 触发收紧: {analysis['候选③ 触发收紧(仅 base≥X 扇出)']}")
    print(f"候选② 变体惩罚: {analysis['候选② 变体惩罚(变体来源 −δ)']}")
    print(f"候选① 佐证要求: {analysis['候选① 佐证要求(原问题词项)']}")
    print(f"\n报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
