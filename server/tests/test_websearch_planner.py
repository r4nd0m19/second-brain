"""F4 决策器：触发 / 不触发 / 容错 / 仅当前问题（隐私边界 FR-006）。"""

from app.chat.llm import LLMError
from app.websearch import planner as planner_module


class _FakeLLM:
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or {"content": "", "tool_calls": []}
        self.error = error
        self.calls: list = []
        self.tools: list = []

    async def stream_chat(self, messages):  # pragma: no cover - 未使用
        raise NotImplementedError
        yield {}

    async def complete_with_tools(self, messages, tools, tool_choice="auto", max_tokens=200):
        self.calls.append(messages)
        self.tools.append(tools)
        if self.error:
            raise self.error
        return self.result


async def test_decide_search_true_and_only_current_question(monkeypatch) -> None:
    fake = _FakeLLM(
        result={"content": "", "tool_calls": [{"name": "web_search", "arguments": {"query": "upwork 项目"}}]}
    )
    monkeypatch.setattr(planner_module, "get_llm_client", lambda: fake)

    decision = await planner_module.decide_search("最近有没有适合我的 upwork 项目")
    assert decision == {"search": True, "query": "upwork 项目"}

    # 仅当前问题：system + user 两条，user 即原文（无历史/无本地库内容拼接）
    messages = fake.calls[0]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "最近有没有适合我的 upwork 项目"}
    # 工具协议：web_search 函数已声明
    assert fake.tools[0][0]["function"]["name"] == "web_search"


async def test_decide_search_false_no_tool(monkeypatch) -> None:
    fake = _FakeLLM(result={"content": "NO_SEARCH", "tool_calls": []})
    monkeypatch.setattr(planner_module, "get_llm_client", lambda: fake)
    assert (await planner_module.decide_search("什么是快速排序"))["search"] is False


async def test_decide_search_llm_error_fault_tolerant(monkeypatch) -> None:
    fake = _FakeLLM(error=LLMError("down"))
    monkeypatch.setattr(planner_module, "get_llm_client", lambda: fake)
    assert (await planner_module.decide_search("随便问问"))["search"] is False


async def test_decide_search_query_truncated(monkeypatch) -> None:
    fake = _FakeLLM(
        result={"content": "", "tool_calls": [{"name": "web_search", "arguments": {"query": "长" * 90}}]}
    )
    monkeypatch.setattr(planner_module, "get_llm_client", lambda: fake)
    decision = await planner_module.decide_search("q")
    assert decision["search"] is True and len(decision["query"]) == 70


async def test_decide_search_empty_query_ignored(monkeypatch) -> None:
    fake = _FakeLLM(
        result={"content": "", "tool_calls": [{"name": "web_search", "arguments": {"query": "  "}}]}
    )
    monkeypatch.setattr(planner_module, "get_llm_client", lambda: fake)
    assert (await planner_module.decide_search("q"))["search"] is False


def test_decoupled_signature() -> None:
    """US3 解耦：decide_search 入参仅当前问题文本。"""
    import inspect

    assert list(inspect.signature(planner_module.decide_search).parameters) == ["user_text"]
