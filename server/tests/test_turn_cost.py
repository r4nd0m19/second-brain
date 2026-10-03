"""全成本聚合（T079）：累加器分隔/合计 + complete_chat 计费钩子。"""

from app import costing
from app.chat.llm import complete_chat


class _FakeClient:
    async def stream_chat(self, _messages):
        yield {"type": "token", "text": "好"}
        yield {
            "type": "usage",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_cache_hit_tokens": 0,
            },
        }


async def test_accumulator_total_and_breakdown():
    turn = costing.start_turn()
    costing.add_llm(0.002)
    costing.add_web(0.01)
    costing.add_retrieval(0.0001)
    assert round(turn.total_cny, 6) == 0.0121
    assert turn.breakdown() == {"llm": 0.002, "web": 0.01, "retrieval": 0.0001}


async def test_complete_chat_counts_into_turn():
    turn = costing.start_turn()
    text = await complete_chat(_FakeClient(), [{"role": "user", "content": "x"}])
    assert text == "好"
    assert turn.llm_cny > 0  # 分档定价含峰谷倍率，不断言具体值


def test_adds_without_turn_context_are_noop():
    """不在回合上下文（如入库管线的 embedding 调用）→ 静默跳过、不抛错。"""
    costing._current.set(None)
    costing.add_llm(1.0)
    costing.add_web(1.0)
    costing.add_retrieval(1.0)
    assert costing.current() is None
