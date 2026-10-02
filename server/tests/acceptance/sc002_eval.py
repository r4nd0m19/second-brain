#!/usr/bin/env python3
"""SC-002 样例题集评测（T040）：真实链路跑批（检索+LLM+出处标注），输出通过率。

用法::

    cd server && .venv/bin/python tests/acceptance/sc002_eval.py [--base-url http://localhost:8000]

说明：
- 需要服务已启动、题库已入库（questions.yaml 中的题都基于库内两份资料）。
- 评测会向库中写入对话记录（含兜底回写），**跑完自动删除评测对话及其回写**（`--keep` 可保留用于排查）。
  自清理很重要：兜底回写会进语料，不清理会污染后续评测与真实检索。
- 判定口径：hit 类 = source_type=kb ＋ 出处文档匹配 ＋ 关键词任一命中；整体 hit 通过率 ≥80% 为 PASS。
- 报告同时落盘 tests/acceptance/sc002_report.json，便于追踪。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings  # noqa: E402

QUESTIONS_FILE = Path(__file__).parent / "questions.yaml"
REPORT_FILE = Path(__file__).parent / "sc002_report.json"
RECALL_DELAY_S = 8  # 等兜底回写入库（异步）后再重问


async def login(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"username": settings.admin_username, "password": settings.admin_password},
    )
    if resp.status_code != 204:
        raise SystemExit(f"登录失败（{resp.status_code}）——请检查 .env 账号密码与服务状态")


async def ask(client: httpx.AsyncClient, question: str, conv_id: str | None) -> dict:
    """提问并收集 meta / 正文 / 出处（所有评测共用同一对话，避免污染历史侧栏）。"""
    meta: dict = {}
    answer = ""
    body = {"message": question}
    if conv_id:
        body["conversation_id"] = conv_id
    async with client.stream("POST", "/api/chat", json=body) as resp:
        resp.raise_for_status()
        event = "message"
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                try:
                    payload = json.loads(line.split(":", 1)[1].strip())
                except json.JSONDecodeError:
                    continue
                if event == "meta":
                    meta = payload
                elif event == "token":
                    answer += payload.get("text", "")
    return {
        "source_type": meta.get("source_type"),
        "citations": meta.get("citations") or [],
        "answer": answer,
        "conversation_id": meta.get("conversation_id"),
    }


def score(entry: dict, result: dict) -> tuple[bool, str]:
    category = entry["category"]
    if category == "hit":
        if result["source_type"] != "kb":
            return False, f"来源应为 kb，实为 {result['source_type']}"
        doc_ok = any(
            entry["expected_document"] in (c.get("document_name") or "")
            for c in result["citations"]
        )
        if not doc_ok:
            names = [c.get("document_name", "?")[:20] for c in result["citations"]]
            return False, f"出处未指向 {entry['expected_document']}（citations: {names or '空'}）"
        kws = entry.get("expected_keywords") or []
        if kws and not any(kw in result["answer"] for kw in kws):
            return False, f"回答未含关键词 {kws}"
        return True, "kb ＋ 出处匹配"
    if category == "fallback":
        if result["source_type"] in {"model_knowledge", "prior_conversation"}:
            return True, f"非库来源（{result['source_type']}）✓"
        return False, f"应为兜底，实为 {result['source_type']}"
    if category == "recall":
        if result["source_type"] == "prior_conversation":
            return True, "二次命中 prior_conversation ✓"
        return False, f"应为 prior_conversation，实为 {result['source_type']}"
    return False, "未知题类"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--keep", action="store_true", help="保留评测对话（默认跑完自动清理）")
    args = parser.parse_args()

    spec = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = spec["questions"]

    results: list[dict] = []
    conv_id: str | None = None
    async with httpx.AsyncClient(base_url=args.base_url, timeout=180) as client:
        await login(client)

        for entry in questions:
            if entry["category"] == "recall":
                await asyncio.sleep(RECALL_DELAY_S)  # 等待兜底回写入库
            t0 = time.monotonic()
            try:
                result = await ask(client, entry["question"], conv_id)
                conv_id = result.get("conversation_id") or conv_id
            except Exception as exc:  # noqa: BLE001 —— 评测继续，记录失败
                result = {
                    "source_type": None,
                    "citations": [],
                    "answer": f"<错误: {exc}>",
                    "conversation_id": None,
                }
            passed, note = score(entry, result)
            cost = time.monotonic() - t0
            results.append(
                {
                    "id": entry["id"],
                    "category": entry["category"],
                    "question": entry["question"],
                    "passed": passed,
                    "note": note,
                    "source_type": result["source_type"],
                    "seconds": round(cost, 1),
                    "answer_head": result["answer"][:80],
                }
            )
            mark = "✅" if passed else "❌"
            print(f"{mark} [{entry['id']}] {entry['question'][:38]}… → {note}")

        # 自清理：删除评测对话（级联删除其兜底回写文档与向量），避免污染语料
        if conv_id and not args.keep:
            await asyncio.sleep(2)  # 留出最后一轮回写的完成窗口
            resp = await client.delete(f"/api/conversations/{conv_id}")
            print(f"\n评测对话已清理（HTTP {resp.status_code}）")

    hit = [r for r in results if r["category"] == "hit"]
    hit_pass = sum(1 for r in hit if r["passed"])
    hit_rate = hit_pass / len(hit) if hit else 0
    fb = [r for r in results if r["category"] == "fallback"]
    rc = [r for r in results if r["category"] == "recall"]

    print("\n──── SC-002 评测汇总 ────")
    print(f"命中类：{hit_pass}/{len(hit)}（{hit_rate:.0%}，口径 ≥80%）")
    print(f"兜底类：{sum(1 for r in fb if r['passed'])}/{len(fb)}")
    print(f"二次命中：{sum(1 for r in rc if r['passed'])}/{len(rc)}")
    verdict = "PASS" if hit_rate >= 0.8 else "FAIL"
    print(f"结论：{verdict}")

    REPORT_FILE.write_text(
        json.dumps({"verdict": verdict, "hit_rate": hit_rate, "results": results},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"报告已写入 {REPORT_FILE.relative_to(SERVER_ROOT)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
