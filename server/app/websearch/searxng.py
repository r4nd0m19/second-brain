"""SearXNG 自托管搜索客户端（T085/R39）：零成本联网检索源（全部自建）。

本机 docker 部署（deploy/docker-compose.yml 的 searxng 服务，127.0.0.1:8888，JSON 接口已开）。
实机裁剪引擎集（网络受限环境）：sogou（中英质量最好）+ bing（base_url=cn.bing.com）+ 360search。
返回结构与付费客户端一致（WebSearchResult），上层（重排过滤/读页/引用/成本）完全复用；
免费源不计每日护栏、不计成本（`paid=False`，add_web 不在本模块调用）。
"""

from __future__ import annotations

import logging

import httpx

from app.websearch.client import WebSearchError, WebSearchResult

logger = logging.getLogger(__name__)

MAX_RESULTS = 20  # 单查询候选上限（免费源多取候选 → 交给重排过滤精选，代价仅为过滤开销）


class SearXNGClient:
    """自托管 SearXNG（元搜索）客户端；接口与 WebSearchClient.search 对齐。"""

    paid = False  # 免费源：orchestrator 不计数护栏；成本恒 0

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,  # 测试注入（MockTransport）
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    async def search(self, query: str, count: int) -> list[WebSearchResult]:
        """元搜索（多引擎由容器侧并行完成）；失败抛 WebSearchError（上层静默降级）。

        count 仅作参考：免费源统一返回更多候选（≤MAX_RESULTS），由重排过滤截取。
        """
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    params={"q": query.strip(), "format": "json"},
                )
        except httpx.HTTPError as exc:
            raise WebSearchError(f"SearXNG 请求失败：{exc}") from exc
        if response.status_code != 200:
            raise WebSearchError(
                f"SearXNG 返回 {response.status_code}: {response.text[:200]}"
            )

        results: list[WebSearchResult] = []
        for item in (response.json().get("results") or [])[:MAX_RESULTS]:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            engines = item.get("engines") or []
            results.append(
                WebSearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url,
                    snippet=(item.get("content") or "").strip(),
                    site_name=", ".join(engines) if engines else None,
                    published_at=item.get("publishedDate") or None,
                )
            )
        return results
