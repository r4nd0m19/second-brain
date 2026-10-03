"""DeepSeek 服务端搜索客户端（T086/R40）：官方 Anthropic 兼容端点 + web_search 服务端工具。

调用方式（2026-10-03 真实 key 实测）：`POST {base}/anthropic/v1/messages`，Bearer 复用
`llm_api_key`（同一 DeepSeek 账户、零新凭据）；请求声明服务端工具
`tools:[{type:"web_search_20250305", name:"web_search"}]`，由 DeepSeek 服务端执行搜索。
响应 `content` 块序：thinking → server_tool_use(查询词) → web_search_tool_result(标题/URL/加密正文) → text。

与其它源接口对齐（`search(query, count) -> list[WebSearchResult]`），上层（重排过滤/读页/引用/
成本/护栏）完全复用。三点差异：
- 计费为 **token 制**（无按次费）：按官方分档单价计入 web 成本；`paid=True` 计入每日护栏；
- 结果**无明文摘要**（正文字段为密文、仅模型可见）→ snippet 留空：重排按标题评、正文由读页管线补齐；
- 模型会自动改写/补全查询（如中→英），单次调用可能执行 1-2 轮服务端搜索
  （usage.server_tool_use.web_search_requests 可核）。
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.chat.llm import estimate_cost_cny_anthropic
from app.costing import add_web
from app.websearch.client import WebSearchError, WebSearchResult

logger = logging.getLogger(__name__)

MAX_RESULTS = 20  # 与 SearXNG 同口径：多取候选 → 交给重排过滤精选
TOOL_TYPE = "web_search_20250305"
QUERY_MAX_CHARS = 70  # 与智谱源同口径；规划器已截断，客户端再兜底


class DeepSeekWebSearch:
    """DeepSeek 服务端搜索（token 计费；接口与 WebSearchClient.search 对齐）。"""

    paid = True  # 计费源：计入每日护栏与 web 成本（token 制）

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "deepseek-flash",
        timeout: float = 30.0,
        max_tokens: int = 256,
        transport: httpx.AsyncBaseTransport | None = None,  # 测试注入（MockTransport）
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.transport = transport

    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        """服务端联网搜索；失败抛 WebSearchError（上层静默降级）。

        count 仅作参考：服务端检索条数不可控，统一返回全部候选（≤MAX_RESULTS）交重排过滤。
        """
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"请联网搜索：{query.strip()[:QUERY_MAX_CHARS]}。"
                        "（只要执行搜索并返回结果，不要展开回答）"
                    ),
                }
            ],
            "tools": [{"type": TOOL_TYPE, "name": "web_search", "max_uses": 2}],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "anthropic-version": "2023-06-01",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:  # 超时/连接错误
            raise WebSearchError(f"DeepSeek 搜索请求失败：{exc}") from exc
        if response.status_code != 200:
            raise WebSearchError(
                f"DeepSeek 搜索返回 {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        usage = data.get("usage")
        if isinstance(usage, dict):  # 无论结果如何，token 已消耗（失败形态也已计费）
            add_web(estimate_cost_cny_anthropic(usage))

        results: list[WebSearchResult] = []
        seen: set[str] = set()
        tool_error: str | None = None
        for block in data.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
                continue
            content = block.get("content")
            if isinstance(content, dict):  # 错误形态：web_search_tool_result_error
                tool_error = str(content.get("error_code") or content.get("type") or "error")
                continue
            for item in content or []:
                url = (item.get("url") or "").strip() if isinstance(item, dict) else ""
                if not url or url in seen:
                    continue  # 多轮搜索重复 URL：去重保序
                seen.add(url)
                results.append(
                    WebSearchResult(
                        title=(item.get("title") or "").strip(),
                        url=url,
                        snippet="",  # 无明文摘要（密文仅模型可见）→ 读页管线补正文
                        site_name=urlparse(url).netloc or None,
                        published_at=item.get("page_age") or None,
                    )
                )
                if len(results) >= MAX_RESULTS:
                    return results
        if not results and tool_error:
            raise WebSearchError(f"DeepSeek 搜索工具错误：{tool_error}")
        return results
