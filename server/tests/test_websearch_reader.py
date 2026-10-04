"""联网读页（R38）：正文提取 / 段落级筛选 / 抓取失败降级（不触网）。
T093 加固用例：SSRF 预检（内网/回环/元数据端点）、重定向逐跳校验、流式字节上限、总时限。"""

import asyncio

import httpx

from app.config import settings
from app.websearch import reader

_SENTENCE = "这是正文段落，讲述平台需求量最大的技能类别与增长趋势，并给出统计口径与数据来源说明，供参考对比。"

# 公网字面 IP（example.com）：is_global 为真且无需 DNS，作为"合法目标"测试桩
_PUBLIC = "http://93.184.216.34"

SAMPLE_HTML = (
    "<html><head><title>测试页</title></head><body>"
    "<nav>首页 关于我们 联系方式 登录注册</nav>"
    "<article><h1>技能与需求报告</h1>"
    + "".join(f"<p>{_SENTENCE * 3}（第 {i} 段）</p>" for i in range(1, 6))
    + "</article><footer>版权所有 备案号 12345</footer></body></html>"
)


def test_extract_main_text_strips_nav():
    text = reader.extract_main_text(SAMPLE_HTML)
    assert text
    assert "需求量最大的技能" in text
    assert "关于我们" not in text  # 导航噪声被 precision 模式剔除


def test_split_paragraphs_filters_short():
    paragraphs = reader.split_paragraphs("短\n" + "长" * 40 + "\n\n" + "另一个足够长的段落" * 5)
    assert paragraphs
    assert all(len(p) >= 30 for p in paragraphs)


async def test_digest_truncates_without_rerank(monkeypatch):
    monkeypatch.setattr(settings, "web_search_digest_max_chars", 60)
    monkeypatch.setattr(settings, "rerank_enabled", False)
    text = "\n".join("段落内容" * 30 for _ in range(5))
    digest = await reader.digest_page("问题", text)
    assert 0 < len(digest) <= 60


async def test_digest_picks_relevant_paragraphs(monkeypatch):
    monkeypatch.setattr(settings, "web_search_digest_max_chars", 90)
    monkeypatch.setattr(settings, "web_search_digest_max_paragraphs", 2)
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "embedding_api_key", "test")
    para_a = "无关内容：" + "甲" * 40
    para_b = "相关问题答案：" + "乙" * 40
    para_c = "另一个无关：" + "丙" * 40

    async def fake_rerank(_query: str, docs: list[str]) -> list[float]:
        return [0.9 if "答案" in d else 0.1 for d in docs]

    monkeypatch.setattr(reader, "rerank_texts", fake_rerank)
    digest = await reader.digest_page("问题", f"{para_a}\n{para_b}\n{para_c}")
    assert "乙" in digest
    assert "甲" not in digest


async def test_read_pages_fetch_failure_skips_entry(monkeypatch):
    monkeypatch.setattr(settings, "web_search_reader_max_pages", 3)

    async def fake_fetch(_client, url: str) -> str | None:
        return SAMPLE_HTML if url.endswith("/ok") else None

    monkeypatch.setattr(reader, "fetch_html", fake_fetch)
    digests = await reader.read_pages(
        "问题", ["https://a.example/ok", "https://b.example/bad"]
    )
    assert "https://a.example/ok" in digests
    assert "https://b.example/bad" not in digests  # 失败条目由调用方回退搜索摘要


# ── T093：SSRF 预检 / 重定向逐跳校验 / 流式字节上限 / 总时限 ──


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


async def test_fetch_blocks_private_addresses_before_any_request():
    """内网/回环/链路本地/云元数据端点：预检即拒，一个请求都不发出。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"})

    async with _mock_client(handler) as client:
        for url in (
            "http://127.0.0.1/",
            "http://192.168.1.10/",
            "http://10.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost/x",
            "file:///etc/passwd",
        ):
            assert await reader.fetch_html(client, url) is None, url
    assert calls == []


async def test_fetch_blocks_redirect_to_private():
    """302 指向内网 → 拦在第二跳之前（防重定向绕过预检）。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == f"{_PUBLIC}/":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="<html>不该到这</html>", headers={"content-type": "text/html"})

    async with _mock_client(handler) as client:
        assert await reader.fetch_html(client, f"{_PUBLIC}/") is None
    assert calls == [f"{_PUBLIC}/"]  # 内网目标未被请求


async def test_fetch_blocks_https_to_http_downgrade():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": f"{_PUBLIC}/ok"})

    async with _mock_client(handler) as client:
        assert await reader.fetch_html(client, "https://93.184.216.34/") is None
    assert len(calls) == 1  # 降级目标未被请求


async def test_fetch_public_redirect_chain_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/start"):
            return httpx.Response(302, headers={"location": f"{_PUBLIC}/final"})
        return httpx.Response(
            200, text="<html><body><p>正文</p></body></html>", headers={"content-type": "text/html"}
        )

    async with _mock_client(handler) as client:
        html = await reader.fetch_html(client, f"{_PUBLIC}/start")
    assert html is not None and "正文" in html


async def test_fetch_aborts_over_byte_cap_mid_stream(monkeypatch):
    """gzip 炸弹/超大页：流式累计解码字节，超上限即断（不再"先全量入内存再查"）。"""
    monkeypatch.setattr(settings, "web_search_page_max_bytes", 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>" + b"x" * 5000, headers={"content-type": "text/html"}
        )

    async with _mock_client(handler) as client:
        assert await reader.fetch_html(client, f"{_PUBLIC}/big") is None


async def test_read_pages_total_timeout(monkeypatch):
    """慢速滴流防线：单页抓取总时限（per-phase 超时会被无限续命）。"""
    monkeypatch.setattr(settings, "web_search_page_total_timeout_s", 0.05)

    async def slow_fetch(_client, _url: str) -> str | None:
        await asyncio.sleep(5)
        return "<html>x</html>"

    monkeypatch.setattr(reader, "fetch_html", slow_fetch)
    digests = await reader.read_pages("问题", [f"{_PUBLIC}/slow"])
    assert digests == {}
