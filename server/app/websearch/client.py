"""联网搜索客户端（F4）：可替换协议 + 智谱实现（httpx；不新增第三方库）。

契约见 specs/004-web-search/contracts/web-search.md：
- 智谱 `POST /api/paas/v4/web_search`（Bearer）；响应 `search_result[]`（title/link/content/media/publish_date）
- 失败一律抛 WebSearchError（调用方降级，绝不影响问答）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings
from app.costing import add_web

ZHIPU_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
QUERY_MAX_CHARS = 70  # 智谱建议 ≤70 字符


class WebSearchError(RuntimeError):
    """搜索服务不可用 / 返回异常（超时、HTTP 错误、错误码 1701/1702 等）。"""


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    site_name: str | None = None
    published_at: str | None = None


class WebSearchClient(Protocol):
    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        """搜索网页；失败抛 WebSearchError。"""


class ZhipuWebSearch:
    """智谱 Web Search 实现（引擎档位/超时/时间范围由配置驱动）。

    链接覆盖策略（2026-10-02 实测）：
    - link 字段按 **引擎 × 查询** 确定性缺失（std/pro 对部分查询 0/5；sogou/quark 全覆盖）；
    - 计费按调用次数、与 count 无关 → 首次请求 **2×count**（≤50）并只取有链接条目；
    - 主引擎零可用链接时，用兜底引擎再试一次（默认 search_pro_sogou；空串=禁用）。
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float = 5.0,
        engine: str = "search_std",
        freshness: str = "noLimit",
        fallback_engine: str = "",
        transport: httpx.AsyncBaseTransport | None = None,  # 测试注入（MockTransport）
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.engine = engine
        self.freshness = freshness
        self.fallback_engine = fallback_engine
        self.transport = transport

    async def _request(self, engine: str, query: str, count: int) -> list[WebSearchResult]:
        payload = {
            "search_query": query.strip()[:QUERY_MAX_CHARS],
            "search_engine": engine,
            "count": count,
            "content_size": "medium",
            "search_recency_filter": self.freshness,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.post(
                    ZHIPU_SEARCH_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:  # 超时/连接错误
            raise WebSearchError(f"搜索请求失败：{exc}") from exc

        if response.status_code != 200:
            # 错误体可能含 1701（并发上限）/1702（无可用引擎）等业务码
            raise WebSearchError(f"搜索返回 {response.status_code}: {response.text[:200]}")

        # 全成本（T079 / R36）：智谱按调用次数计费（失败请求不计费——非 200 已在上方抛出）
        add_web(
            settings.price_web_search_std_cny
            if engine == "search_std"
            else settings.price_web_search_pro_cny
        )

        data = response.json()
        results: list[WebSearchResult] = []
        for item in data.get("search_result") or []:
            results.append(
                WebSearchResult(
                    title=(item.get("title") or "").strip(),
                    url=(item.get("link") or "").strip(),
                    snippet=(item.get("content") or item.get("snippet") or "").strip(),
                    site_name=(item.get("media") or None) or None,
                    published_at=item.get("publish_date") or None,
                )
            )
        return results

    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        requested = min(50, max(count, count * 2))
        linked = [r for r in await self._request(self.engine, query, requested) if r.url]
        if linked:
            return linked[:count]
        if self.fallback_engine:
            linked = [
                r for r in await self._request(self.fallback_engine, query, count) if r.url
            ]
            return linked[:count]
        return []


def get_paid_web_search() -> ZhipuWebSearch | None:
    """付费源（智谱）工厂：未配置 key → None；仅 web_search_paid_fallback 开启时由 orchestrator 使用。"""
    if not settings.web_search_api_key:
        return None
    return ZhipuWebSearch(
        api_key=settings.web_search_api_key,
        timeout=settings.web_search_timeout_s,
        engine=settings.web_search_engine,
        freshness=settings.web_search_freshness,
        fallback_engine=settings.web_search_fallback_engine,
    )


def get_web_search():
    """按配置返回搜索源（R39/T085；T086 增 deepseek）：searxng=自建免费（默认）；
    deepseek=官方服务端搜索（复用 llm_api_key，token 计费）；zhipu=付费 API。

    各源接口对齐（`search(query, count) -> list[WebSearchResult]`；计费源带 `paid=True` 标记）；
    未配置（缺 key）→ None（能力关闭，FR-004）。
    """
    if settings.web_search_provider == "searxng":
        from app.websearch.searxng import SearXNGClient  # 延迟导入避免环

        return SearXNGClient(
            base_url=settings.searxng_base_url, timeout=settings.searxng_timeout_s
        )
    if settings.web_search_provider == "deepseek":
        from app.websearch.deepseek import DeepSeekWebSearch  # 延迟导入避免环

        if not settings.llm_api_key:
            return None  # 服务端搜索复用 llm key：缺 key → 能力关闭
        return DeepSeekWebSearch(
            api_key=settings.llm_api_key,
            base_url=settings.deepseek_search_base_url
            or f"{settings.llm_base_url.rstrip('/')}/anthropic",
            model=settings.deepseek_search_model,
            timeout=settings.deepseek_search_timeout_s,
            max_tokens=settings.deepseek_search_max_tokens,
        )
    return get_paid_web_search()
