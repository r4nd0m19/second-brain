"""网页正文入库（F2）：Markdown 标题分块器 —— 正文已在浏览器端提取，免 Docling 解析。

分块规则（data-model.md「chunks 复用」）：
- 按标题层级维护 heading_path（" > " 连接），同级/更高级标题出现时回退层级；
- 段落聚合到长度上限（默认 1200 字符）即切块；超长段落按行粒度切分；
- page/chapter/paragraph 均为 None（网页无页码语义）。
"""

from __future__ import annotations

import re

from app.ingestion.parser import ChunkDraft

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
DEFAULT_MAX_CHARS = 1200


def chunk_markdown(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[ChunkDraft]:
    headings: list[str] = []
    drafts: list[ChunkDraft] = []
    chunk_parts: list[str] = []  # 当前块内的段落
    para: list[str] = []  # 当前段落的行

    def flush_para() -> None:
        nonlocal para
        if para:
            chunk_parts.append(" ".join(para))
            para = []

    def total_len() -> int:
        return sum(len(p) for p in chunk_parts) + sum(len(line) for line in para)

    def flush_chunk() -> None:
        nonlocal chunk_parts
        flush_para()
        content = "\n\n".join(chunk_parts).strip()
        if content:
            drafts.append(
                ChunkDraft(content=content, heading_path=" > ".join(headings) or None)
            )
        chunk_parts = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _HEADING_RE.match(line)
        if match:
            flush_chunk()
            level = len(match.group(1))
            del headings[level - 1 :]  # 回退到该层级，替换同级标题
            headings.append(match.group(2))
            continue
        if not line:
            flush_para()
            if total_len() >= max_chars:
                flush_chunk()
            continue
        # 超长行硬切（实测 2026-10-02：某些页面拖出的正文整页无换行，单行可数万字符 →
        # 整行成一块会超出 embedding 输入上限，服务端返回 400）
        while len(line) > max_chars:
            para.append(line[:max_chars])
            line = line[max_chars:]
            flush_chunk()
        para.append(line)
        if total_len() >= max_chars:
            flush_chunk()  # 行粒度切分

    flush_chunk()
    return drafts
