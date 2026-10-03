"""V4 思考档行为（T088）：小调用关思考 / 答案调用开思考（思维链事件） / 工具调用关思考。"""

import json

import httpx

from app.chat.llm import OpenAICompatLLM


def _sse(chunks: list[dict]) -> bytes:
    body = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks)
    return (body + "data: [DONE]\n\n").encode()


def _client(handler) -> OpenAICompatLLM:
    return OpenAICompatLLM(
        base_url="https://api.deepseek.com",
        api_key="k",
        model="deepseek-flash",
        transport=httpx.MockTransport(handler),
    )


async def test_small_calls_disable_thinking_and_skip_reasoning_events():
    """小调用（complete_chat 等，thinking 默认关）：显式关思考、不产生 thinking 事件。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            content=_sse([{"choices": [{"delta": {"content": "好"}}]}]),
            headers={"content-type": "text/event-stream"},
        )

    events = [
        e async for e in _client(handler).stream_chat([{"role": "user", "content": "q"}])
    ]
    compact = captured["body"].replace(" ", "")
    assert '"thinking":{"type":"disabled"}' in compact
    assert '"effort"' not in compact
    assert events == [{"type": "token", "text": "好"}]


async def test_answer_calls_enable_thinking_and_forward_reasoning():
    """答案调用（thinking=True）：开思考档 + effort 档位；reasoning_content 增量 → thinking 事件。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            content=_sse(
                [
                    {"choices": [{"delta": {"reasoning_content": "想…"}}]},
                    {"choices": [{"delta": {"content": "答"}}]},
                ]
            ),
            headers={"content-type": "text/event-stream"},
        )

    events = [
        e
        async for e in _client(handler).stream_chat(
            [{"role": "user", "content": "q"}], thinking=True
        )
    ]
    compact = captured["body"].replace(" ", "")
    assert '"thinking":{"type":"enabled"}' in compact
    assert '"effort":"high"' in compact  # config 默认档（llm_answer_effort）
    assert events == [{"type": "thinking", "text": "想…"}, {"type": "token", "text": "答"}]


async def test_complete_with_tools_disables_thinking():
    """规划器工具调用：关思考（否则思维链吃满 max_tokens=200，工具调用为空）。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "", "tool_calls": []}}]}
        )

    await _client(handler).complete_with_tools([{"role": "user", "content": "q"}], tools=[])
    assert '"thinking":{"type":"disabled"}' in captured["body"].replace(" ", "")
