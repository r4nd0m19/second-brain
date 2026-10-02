"""F4 智谱搜索客户端：解析 / 错误码 / 超时 / 工厂（未配 key → None）。"""

import httpx

from app.config import settings
from app.websearch.client import WebSearchError, ZhipuWebSearch, get_web_search


def _ok_body() -> dict:
    return {
        "id": "x",
        "search_result": [
            {
                "title": "标题A",
                "link": "https://a.example/1",
                "content": "摘要A",
                "media": "站点A",
                "publish_date": "2026-10-01",
            },
            {"title": "标题B", "link": "https://b.example/2", "content": "", "media": None},
            {"title": "无链接应忽略", "link": "", "content": "忽略"},
        ],
    }


def _client(handler) -> ZhipuWebSearch:
    return ZhipuWebSearch(api_key="k", transport=httpx.MockTransport(handler))


async def test_parse_success_and_request_shape() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=_ok_body())

    results = await _client(handler).search("  查询词  ", 5)
    assert [r.url for r in results] == ["https://a.example/1", "https://b.example/2"]
    assert results[0].title == "标题A" and results[0].snippet == "摘要A"
    assert results[0].site_name == "站点A" and results[0].published_at == "2026-10-01"
    assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/web_search"
    assert captured["auth"] == "Bearer k"
    compact = captured["body"].replace(" ", "")
    assert '"search_query":"查询词"' in compact
    assert '"content_size":"medium"' in compact
    assert '"count":10' in compact  # 2× 取样（计费按次，与 count 无关）


async def test_zero_link_falls_back_to_fallback_engine() -> None:
    """主引擎零链接 → 兜底引擎再试一次（2026-10-02 实测：link 按引擎×查询确定性缺失）。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        calls.append("sogou" if "search_pro_sogou" in body else "std")
        if "search_pro_sogou" in body:
            return httpx.Response(200, json={"search_result": [
                {"title": "搜狐结果", "link": "https://www.sohu.com/a/1", "content": "摘要"}]})
        return httpx.Response(200, json={"search_result": [
            {"title": "无链接", "link": "", "content": "摘要X"}]})

    client = ZhipuWebSearch(api_key="k", fallback_engine="search_pro_sogou",
                            transport=httpx.MockTransport(handler))
    results = await client.search("查询", 5)
    assert calls == ["std", "sogou"]
    assert [r.url for r in results] == ["https://www.sohu.com/a/1"]


async def test_zero_link_without_fallback_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"search_result": [{"title": "无链接", "link": "", "content": "x"}]})

    client = ZhipuWebSearch(api_key="k", transport=httpx.MockTransport(handler))
    assert await client.search("查询", 5) == []


async def test_prefers_linked_items_and_slices_to_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        items = [
            {"title": f"有链接{i}", "link": f"https://l{i}.example/", "content": "s"}
            for i in range(4)
        ] + [{"title": "无链接", "link": "", "content": "s"}]
        return httpx.Response(200, json={"search_result": items})

    results = await _client(handler).search("查询", 2)
    assert [r.url for r in results] == ["https://l0.example/", "https://l1.example/"]


async def test_query_truncated_to_70_chars() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"search_result": []})

    await _client(handler).search("长" * 100, 5)
    assert "长" * 70 in captured["body"] and "长" * 71 not in captured["body"]


async def test_http_error_and_business_code() -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "1002", "message": "Invalid API key"}})

    try:
        await _client(unauthorized).search("q", 5)
        raise AssertionError("应抛 WebSearchError")
    except WebSearchError as exc:
        assert "401" in str(exc)

    def no_engine(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "1702", "message": "no engine"}})

    try:
        await _client(no_engine).search("q", 5)
        raise AssertionError("应抛 WebSearchError")
    except WebSearchError as exc:
        assert "1702" in str(exc)


async def test_timeout_maps_to_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    try:
        await _client(timeout).search("q", 5)
        raise AssertionError("应抛 WebSearchError")
    except WebSearchError as exc:
        assert "失败" in str(exc)


async def test_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"search_result": []})

    assert await _client(handler).search("q", 5) == []


def test_factory_requires_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "web_search_api_key", "")
    assert get_web_search() is None
    monkeypatch.setattr(settings, "web_search_api_key", "k")
    assert isinstance(get_web_search(), ZhipuWebSearch)


def test_decoupled_signature() -> None:
    """US3 解耦：search 入参仅 (query, count)，无会话/请求上下文。"""
    import inspect

    assert list(inspect.signature(ZhipuWebSearch.search).parameters) == ["self", "query", "count"]
