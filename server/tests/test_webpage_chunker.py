"""T007 DoD：网页 Markdown 标题分块器单测。"""

from app.ingestion.webpage import chunk_markdown


def test_heading_path_and_paragraphs() -> None:
    text = "# 指南\n\n## 安装\n\n步骤一。\n\n## 使用\n\n示例。\n"
    drafts = chunk_markdown(text)
    assert [d.heading_path for d in drafts] == ["指南 > 安装", "指南 > 使用"]
    assert drafts[0].content == "步骤一。"
    assert drafts[1].content == "示例。"
    assert all(d.page is None for d in drafts)


def test_heading_level_pop() -> None:
    text = "# A\n\n## B\n\n正文1\n\n# C\n\n正文2"
    drafts = chunk_markdown(text)
    assert drafts[0].heading_path == "A > B"
    assert drafts[1].heading_path == "C"


def test_long_content_split() -> None:
    text = "## S\n\n" + "\n".join("这是一段很长的文字。" * 5 for _ in range(60))
    drafts = chunk_markdown(text, max_chars=500)
    assert len(drafts) >= 2
    assert all(d.heading_path == "S" for d in drafts)
    assert all(len(d.content) <= 900 for d in drafts)  # 行粒度切分，不超约两个上限


def test_empty_and_no_heading() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown("\n\n  \n") == []
    drafts = chunk_markdown("只有正文，没有标题。")
    assert len(drafts) == 1
    assert drafts[0].heading_path is None
    assert drafts[0].content == "只有正文，没有标题。"


def test_single_giant_line_is_split() -> None:
    """整页无换行（单行数万字符）必须硬切——否则超出 embedding 输入上限（实测 400）。"""
    drafts = chunk_markdown("长" * 5000, max_chars=1000)
    assert len(drafts) >= 5
    assert all(len(d.content) <= 2000 for d in drafts)  # 最坏 ≈ 2×上限（行粒度合并）


def test_giant_line_after_heading() -> None:
    drafts = chunk_markdown("# 标题\n\n" + "很长" * 2000, max_chars=800)
    assert drafts[0].heading_path == "标题"
    assert all(len(d.content) <= 1600 for d in drafts)
