"""SearXNG 客户端（T085）：JSON 解析 / 字段映射 / 错误（不触网，MockTransport）。"""

import httpx
import pytest

from app.websearch.client import WebSearchError
from app.websearch.searxng import SearXNGClient


def _make(handler) -> SearXNGClient:
    return SearXNGClient(base_url="http://searxng.test", transport=httpx.MockTransport(handler))


async def test_search_parses_and_maps_fields():
    payload = {
        "results": [
            {
                "title": "Upwork In-Demand Skills",
                "url": "https://a.example/1",
                "content": "摘要一",
                "engines": ["sogou"],
                "publishedDate": "2026-10-01",
            },
            {"title": "无链接条目", "url": ""},  # 应被丢弃
            {"title": "T2", "url": "https://b.example/2", "content": "", "engines": []},
        ]
    }
    client = _make(lambda _req: httpx.Response(200, json=payload))
    results = await client.search("q", 5)
    assert [r.url for r in results] == ["https://a.example/1", "https://b.example/2"]
    assert results[0].title == "Upwork In-Demand Skills"
    assert results[0].site_name == "sogou"
    assert results[0].published_at == "2026-10-01"
    assert results[1].site_name is None


async def test_search_empty_results():
    client = _make(lambda _req: httpx.Response(200, json={"results": []}))
    assert await client.search("q", 5) == []


async def test_search_http_error_raises():
    client = _make(lambda _req: httpx.Response(500, text="boom"))
    with pytest.raises(WebSearchError):
        await client.search("q", 5)


def test_free_provider_marked_unpaid():
    """免费源标记：orchestrator 据此跳过每日护栏与成本累计（R39）。"""
    assert SearXNGClient(base_url="http://x").paid is False
