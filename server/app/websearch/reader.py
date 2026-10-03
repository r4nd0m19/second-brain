"""联网结果页正文读取（R38/T082）：并行抓取 → trafilatura 正文提取 → 段落级筛选。

业界"搜索+读页"范式：搜索接口只回摘要；对过滤后的前几条结果**并行抓取原页、提取正文、
按用户问题做段落级重排筛选**（复用检索重排器），只把最相关段落注入作答上下文——
引用摘录也因此来自页面正文而非搜索摘要，与主流联网问答产品行为对齐。

受控与降级：页数/单页字符/超时/字节上限/并发均可配置；任一环节失败 → 该条回退搜索摘要
（由调用方处理）；`web_search_reader_max_pages=0` 整体关闭（仅摘要流）。
边界：单用户低频、只读公开页面、不做整站爬取；不绕过反爬（失败即回退），不落盘（004 Non-Goals 精神保留）。
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import trafilatura

from app.config import settings
from app.retrieval.search import rerank_texts

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    """抓取单页 HTML（仅 text/html；字节上限；失败 → None）。"""
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return None  # PDF/二进制等：回退搜索摘要
        if len(resp.content) > settings.web_search_page_max_bytes:
            return None
        return resp.text
    except httpx.HTTPError:
        return None


def extract_main_text(html: str) -> str | None:
    """trafilatura 正文提取（precision 模式：宁缺毋滥，导航噪声不进上下文）。"""
    try:
        text = trafilatura.extract(
            html, output_format="txt", include_comments=False, favor_precision=True
        )
    except Exception:  # 提取失败回退摘要
        logger.warning("trafilatura extract failed", exc_info=True)
        return None
    return text.strip() if text else None


def split_paragraphs(text: str) -> list[str]:
    lines = [p.strip() for p in text.split("\n")]
    return [p for p in lines if len(p) >= 30]


async def digest_page(user_text: str, text: str) -> str:
    """段落级重排筛选：只保留与问题最相关的段落（重排不可用 → 头部截断降级）。"""
    max_chars = settings.web_search_digest_max_chars
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return ""
    joined = "\n".join(paragraphs)
    if len(joined) <= max_chars:
        return joined
    if not settings.rerank_enabled or not settings.embedding_api_key:
        return joined[:max_chars]
    try:
        scores = await rerank_texts(user_text, [p[:500] for p in paragraphs])
    except Exception:  # 筛选失败 → 头部截断
        logger.warning("digest rerank failed; truncate fallback", exc_info=True)
        return joined[:max_chars]
    ranked = sorted(zip(scores, paragraphs), key=lambda item: -item[0])
    picked: list[str] = []
    size = 0
    for _, paragraph in ranked:
        if size + len(paragraph) > max_chars:
            continue
        picked.append(paragraph)
        size += len(paragraph) + 1
        if len(picked) >= settings.web_search_digest_max_paragraphs:
            break
    return "\n".join(picked) if picked else joined[:max_chars]


async def read_pages(user_text: str, urls: list[str]) -> dict[str, str]:
    """并行读取若干结果页 → {url: digest}；失败条目不在结果中（调用方回退搜索摘要）。"""
    if not urls or settings.web_search_reader_max_pages <= 0:
        return {}
    semaphore = asyncio.Semaphore(settings.web_search_fetch_concurrency)
    timeout = httpx.Timeout(settings.web_search_page_timeout_s)

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers={"User-Agent": _UA}
    ) as client:

        async def one(url: str) -> tuple[str, str] | None:
            async with semaphore:
                html = await fetch_html(client, url)
            if not html:
                return None
            text = await asyncio.to_thread(extract_main_text, html)  # 提取是同步 CPU 活
            if not text:
                return None
            digest = await digest_page(user_text, text)
            return (url, digest) if digest else None

        results = await asyncio.gather(*(one(u) for u in urls), return_exceptions=True)

    out: dict[str, str] = {}
    for item in results:
        if isinstance(item, tuple):
            out[item[0]] = item[1]
    return out
