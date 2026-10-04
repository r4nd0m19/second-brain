"""DeepSeek 服务端搜索客户端（T086）：响应块解析 / 去重 / 错误 / token 计费（MockTransport 不触网）。"""

import httpx
import pytest

from app.chat import llm as llm_mod
from app.costing import current, start_turn
from app.websearch.client import WebSearchError
from app.websearch.deepseek import DeepSeekWebSearch


def _ok_body() -> dict:
    return {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": "deepseek-flash",
        "content": [
            {"type": "thinking", "thinking": "…", "signature": "s"},
            {
                "type": "server_tool_use",
                "id": "t1",
                "name": "web_search",
                "input": {"query": "查询"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "t1",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "标题A",
                        "url": "https://a.example/1",
                        "encrypted_content": "xx",
                        "page_age": None,
                    },
                    {
                        "type": "web_search_result",
                        "title": "标题B",
                        "url": "https://b.example/2",
                        "encrypted_content": "xx",
                        "page_age": "2026-10-01",
                    },
                    {
                        "type": "web_search_result",
                        "title": "重复URL",
                        "url": "https://a.example/1",
                        "encrypted_content": "xx",
                        "page_age": None,
                    },
                ],
            },
            {"type": "text", "text": "已搜索"},
        ],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 1000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 50,
            "server_tool_use": {"web_search_requests": 1},
        },
    }


def _make(handler) -> DeepSeekWebSearch:
    return DeepSeekWebSearch(
        api_key="k",
        base_url="https://api.deepseek.com/anthropic",
        transport=httpx.MockTransport(handler),
    )


async def test_parse_dedupe_and_mapping():
    results = await _make(lambda _req: httpx.Response(200, json=_ok_body())).search("查询", 5)
    assert [r.url for r in results] == ["https://a.example/1", "https://b.example/2"]  # 去重保序
    assert results[0].title == "标题A"
    assert results[0].snippet == ""  # 无明文摘要（密文仅模型可见）→ 读页管线补齐
    assert results[0].site_name == "a.example"
    assert results[1].published_at == "2026-10-01"


async def test_request_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=_ok_body())

    await _make(handler).search("  Upwork 需求  ", 5)
    compact = captured["body"].replace(" ", "")
    assert captured["url"] == "https://api.deepseek.com/anthropic/v1/messages"
    assert captured["auth"] == "Bearer k"
    assert '"web_search_20250305"' in compact and '"web_search"' in compact
    assert "Upwork需求" in compact  # strip 后入提示词
    assert '"max_tokens"' not in compact  # T091：不再传上限（供应商默认兜底）


async def test_truncation_logs_warning(caplog):
    """T091：stop_reason=max_tokens → 告警可见（截断不许静默）。"""
    body = _ok_body()
    body["stop_reason"] = "max_tokens"
    with caplog.at_level("WARNING", logger="app.websearch.deepseek"):
        await _make(lambda _req: httpx.Response(200, json=body)).search("q", 5)
    assert any("截断" in r.message for r in caplog.records)


async def test_token_cost_accounted(monkeypatch):
    """token 计费（无按次费）：1000 未命中×1.0 + 50 输出×4.0 每百万 = 0.0012 元。"""
    monkeypatch.setattr(llm_mod, "_is_peak_now", lambda: False)
    start_turn()
    await _make(lambda _req: httpx.Response(200, json=_ok_body())).search("q", 5)
    turn = current()
    assert turn is not None and abs(turn.web_cny - 0.0012) < 1e-12


async def test_tool_error_without_results_raises():
    body = {
        "content": [
            {
                "type": "web_search_tool_result",
                "tool_use_id": "t1",
                "content": {"type": "web_search_tool_result_error", "error_code": "unavailable"},
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 1},
    }
    with pytest.raises(WebSearchError) as exc:
        await _make(lambda _req: httpx.Response(200, json=body)).search("q", 5)
    assert "unavailable" in str(exc.value)


async def test_http_error_and_timeout_raise():
    with pytest.raises(WebSearchError):
        await _make(lambda _req: httpx.Response(429, text="rate limited")).search("q", 5)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(WebSearchError):
        await _make(boom).search("q", 5)


async def test_no_search_blocks_returns_empty():
    """模型未执行搜索（无 web_search_tool_result 块）→ 空列表，由编排层按未取得结果处理。"""
    body = {
        "content": [{"type": "text", "text": "我没有搜索"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    assert await _make(lambda _req: httpx.Response(200, json=body)).search("q", 5) == []


def test_paid_flag():
    """计费源标记：编排层据此计入每日护栏与 web 成本（T086）。"""
    assert DeepSeekWebSearch(api_key="k", base_url="https://x").paid is True
