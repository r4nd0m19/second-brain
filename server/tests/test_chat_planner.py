"""查询规划器（FR-022/R21）：工具调用解析 / 上限 / 未知工具忽略 / 容错 / 隐私边界。"""

from app.chat import planner
from app.chat.llm import LLMError


class _FakeLLM:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {"tool_calls": []}
        self.error = error
        self.messages: list[dict] = []

    async def complete_with_tools(self, messages, tools, tool_choice="auto", max_tokens=0):
        self.messages = messages
        if self.error:
            raise self.error
        return self.result


def _patch_llm(monkeypatch, llm: _FakeLLM) -> None:
    monkeypatch.setattr(planner, "get_llm_client", lambda: llm)


async def test_plan_parses_tool_calls_and_privacy(monkeypatch) -> None:
    llm = _FakeLLM(
        {
            "tool_calls": [
                {"name": "search_library", "arguments": {"query": "康威定律"}},
                {"name": "list_browsing", "arguments": {"time_range": "昨天"}},
            ]
        }
    )
    _patch_llm(monkeypatch, llm)

    calls = await planner.plan_retrieval("问题文本")
    assert [c.name for c in calls] == ["search_library", "list_browsing"]
    assert calls[0].args["query"] == "康威定律"
    # 隐私边界：只发送当前问题（system + user 两条）
    assert [m["role"] for m in llm.messages] == ["system", "user"]
    assert llm.messages[1]["content"] == "问题文本"


async def test_plan_caps_calls_and_skips_unknown_tool(monkeypatch) -> None:
    tool_calls = [
        {"name": "search_library", "arguments": {"query": f"q{i}"}} for i in range(5)
    ]
    tool_calls.insert(1, {"name": "delete_everything", "arguments": {}})
    _patch_llm(monkeypatch, _FakeLLM({"tool_calls": tool_calls}))

    calls = await planner.plan_retrieval("q")
    assert len(calls) == planner.MAX_CALLS
    assert all(c.name == "search_library" for c in calls)


async def test_plan_no_tools_and_llm_error_return_empty(monkeypatch) -> None:
    _patch_llm(monkeypatch, _FakeLLM({"tool_calls": []}))
    assert await planner.plan_retrieval("q") == []

    _patch_llm(monkeypatch, _FakeLLM(error=LLMError("x")))
    assert await planner.plan_retrieval("q") == []


async def test_plan_tolerates_malformed_arguments(monkeypatch) -> None:
    _patch_llm(
        monkeypatch,
        _FakeLLM({"tool_calls": [{"name": "web_search", "arguments": "not-a-dict"}]}),
    )
    calls = await planner.plan_retrieval("q")
    assert len(calls) == 1 and calls[0].args == {}
