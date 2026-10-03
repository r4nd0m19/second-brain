"""回写复用性判定（R18 续三，2026-10-03）：LLM 语义判定替代标记词表；失败保守跳过。

背景：标记词表补过 4 次仍漏"编造型"（虚构浏览记录不含任何标记词）——
语义判定是唯一能同时覆盖 失败说明/个人数据断言/编造 的机制。
"""

from app.chat import writeback
from app.chat.llm import LLMError


def _patch(monkeypatch, *, output: str | None = None, error: Exception | None = None) -> None:
    async def fake_complete(_client, _messages):
        if error is not None:
            raise error
        return output

    monkeypatch.setattr(writeback, "complete_chat", fake_complete)
    monkeypatch.setattr(writeback, "get_llm_client", lambda: None)


async def test_reusable_when_llm_says_yes(monkeypatch) -> None:
    _patch(monkeypatch, output="是")
    assert await writeback.is_reusable_qa("问", "答") is True
    _patch(monkeypatch, output="是")  # 正常知识问答
    assert await writeback.is_reusable_qa("SDD 的核心循环是什么", "规格→计划→任务→实现") is True


async def test_not_reusable_when_llm_says_no(monkeypatch) -> None:
    _patch(monkeypatch, output="否")
    # 编造型（虚构浏览记录）——标记词表时代无法捕获的样本
    assert (
        await writeback.is_reusable_qa(
            "我昨天浏览了什么内容", "你昨天（2025-06-06）浏览了 PyTorch 官方文档…"
        )
        is False
    )


async def test_judgement_failure_skips_conservatively(monkeypatch) -> None:
    _patch(monkeypatch, error=LLMError("x"))
    assert await writeback.is_reusable_qa("问", "答") is False
