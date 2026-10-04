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
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.config import settings
from app.retrieval.search import rerank_texts

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_MAX_REDIRECTS = 5  # 手动重定向逐跳校验（T093）


def _host_is_public(host: str) -> bool:
    """SSRF 防护（T093）：解析全部地址记录，任一非公网（私有/回环/链路本地/CGNAT/保留）即拒。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not addr.is_global:
            return False
    return True


async def _url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return await asyncio.to_thread(_host_is_public, parsed.hostname)


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    """抓取单页 HTML。防护（T093 审计）：仅 http/https；每跳（含重定向目标）解析 IP 拒绝
    非公网地址；禁 https→http 降级；**流式**累计解码后字节（gzip 炸弹在展开计数、超限即断，
    不再"先全量入内存再检查"）；失败 → None（上层回退搜索摘要）。
    注意：client 需以 follow_redirects=False 构建（重定向由此处手动处理）。"""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not await _url_allowed(current):
            logger.info("reader: blocked url (non-public address or bad scheme)")
            return None
        try:
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    target = urljoin(current, location)
                    if urlparse(current).scheme == "https" and urlparse(target).scheme == "http":
                        return None  # 禁降级（T093）
                    current = target
                    continue
                if resp.status_code != 200:
                    return None
                ctype = (resp.headers.get("content-type") or "").lower()
                if "html" not in ctype:
                    return None  # PDF/二进制等：回退搜索摘要
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():  # 解码后字节：压缩炸弹在展开侧计数
                    total += len(chunk)
                    if total > settings.web_search_page_max_bytes:
                        logger.info("reader: page exceeds byte cap; aborted mid-stream")
                        return None
                    chunks.append(chunk)
                return b"".join(chunks).decode(resp.charset_encoding or "utf-8", errors="replace")
        except httpx.HTTPError:
            return None
    return None  # 重定向超过上限


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
        follow_redirects=False,  # 重定向由 fetch_html 手动逐跳校验（T093，防绕过 SSRF 检查）
        timeout=timeout,
        headers={"User-Agent": _UA},
    ) as client:

        async def one(url: str) -> tuple[str, str] | None:
            async with semaphore:
                try:
                    # 总时限（T093）：per-phase 超时会被慢速滴流无限续命；此处兜底整次抓取
                    html = await asyncio.wait_for(
                        fetch_html(client, url),
                        timeout=settings.web_search_page_total_timeout_s,
                    )
                except TimeoutError:
                    logger.info("reader: fetch exceeded total timeout; skipped")
                    return None
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
