"""联网读页（R38）：正文提取 / 段落级筛选 / 抓取失败降级（不触网）。"""

import app.websearch.reader as reader
from app.config import settings

_SENTENCE = "这是正文段落，讲述平台需求量最大的技能类别与增长趋势，并给出统计口径与数据来源说明，供参考对比。"

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
    digest = await reader.digest_page("问题", "\n".join([para_a, para_b, para_c]))
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
