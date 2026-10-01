"""PDF 文本层快通道（T041）：直抽文字层 + 启发式结构，避开 Docling ML 模型。

实测（1240 页技术书）：rect 级抽取 ~3 秒、全流程 <10 秒、内存几十 MB ——
对比 Docling 全量 ML 解析（~14GB 内存 / 20-60 分钟）是数量级差异；
代价：表格结构退化、标题靠字号启发式（详见 research.md R7）。

结构重建（全部为启发式）：
- 行：rect 按 y 分组（间隙 <1.3pt 且非词边界不空格）；空格阈值经实测校准
- 断词拼接：行尾连字符（含该 PDF 的 \\x02 码位）与下行小写起点相连
- 标题：行高相对正文行高分级（1.55x/1.28x/1.12x），章节首行大字排版
  （行尾连字符/逗号、超长句）会被否决回正文
- 页眉/页码：页面边距区（上/下 42pt）小字号行 + 跨页重复行 + 纯页码行
- 表格占比：列间隙行（≥3 片段且存在 ≥12pt 大间隙）统计 → 超过阈值时
  输出 meta 供"可深度解析"提示（保守阈值，宁可漏报不误报）
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import pypdfium2 as pdfium

from app.ingestion.parser import ChunkDraft, UnparseableError

_PAGE_NUM_RE = re.compile(r"^[ivxlcdm\d]{1,6}[.,]?$", re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[。．.!?！？;；])\s+")

CHUNK_TARGET = 700
CHUNK_MAX = 900
CHUNK_MIN_MERGE = 200

_HEAD_RATIOS = ((1.55, 1), (1.28, 2), (1.12, 3))  # 行高/正文字高 ≥ 阈值 → 标题级别
_HEAD_MAX_LEN = 64  # 超过此长度视为正文（章节首行大字排版的句子很长）
_HEAD_END_VETO = ("-", ",", ";", "，", "；")  # 这些行尾特征 → 正文而非标题
_TOC_ENTRY_RE = re.compile(r"\s\d{1,4}$")  # 目录条目特征：以空格 + 页码结尾

_SEP_MIN = 1.3  # 行内片段间隙 ≥ 此值（pt）视为空格（实测：词间 2.2+，连字 0.8-）
_SEP_RATIO = 0.07
_MARGIN_ZONE = 42  # 页面上下边距区（pt）：其中的小字号行视作页眉/页脚

_ROW_COL_GAP = 12  # 表格行特征：行内 ≥12pt 的列间隙
_TABLE_MIN_ROWS = 3  # 一页至少这么多"列行"才算表格页


@dataclass
class _Line:
    page: int
    y: float = 0.0  # 行顶（页面坐标）
    margin: bool = False  # 位于页面上下边距区
    parts: list[tuple[float, float, str]] = field(default_factory=list)
    _height: float = 0.0

    @property
    def height(self) -> float:
        return self._height

    @property
    def x(self) -> float:
        return min(p[0] for p in self.parts) if self.parts else 0.0

    def text(self) -> str:
        parts = sorted(self.parts, key=lambda p: p[0])
        sep_gap = max(_SEP_MIN, _SEP_RATIO * self._height)
        out = parts[0][2]
        prev_right = parts[0][1]
        for left, right, t in parts[1:]:
            out += (" " if (left - prev_right) >= sep_gap else "") + t
            prev_right = right
        return out

    def col_row_gaps(self) -> int:
        """表格行特征：≥3 个实义片段（≥3 字符）且存在大列间隙 → 返回大间隙数，否则 0。"""
        parts = sorted(self.parts, key=lambda p: p[0])
        if len(parts) < 3 or any(len(p[2]) < 3 for p in parts):
            return 0
        big = sum(1 for a, b in pairwise(parts) if (b[0] - a[1]) >= _ROW_COL_GAP)
        return big


def _clean(text: str) -> str:
    """\\x02 为该 PDF 连字符的码位（实测行尾 4660/4674）；其余控制字符剥离。"""
    text = text.replace("\x02", "-")
    return "".join(ch for ch in text if ch >= " " or ch == "-")


def _extract_lines(pdf: pdfium.PdfDocument) -> list[_Line]:
    lines: list[_Line] = []
    for pno in range(len(pdf)):
        page = pdf[pno]
        _, page_h = page.get_size()
        tp = page.get_textpage()
        rects: list[tuple[float, float, float, float, str, bool]] = []
        n = tp.count_rects()
        for i in range(n):
            left, bottom, right, top = tp.get_rect(i)
            text = _clean(" ".join(tp.get_text_bounded(left, bottom, right, top).split()))
            if text:
                margin = top > page_h - _MARGIN_ZONE or bottom < _MARGIN_ZONE
                rects.append((left, bottom, right, top, text, margin))
        tp.close()
        page.close()

        rects.sort(key=lambda r: (-r[3], r[0]))
        page_lines: list[_Line] = []
        for left, bottom, right, top, text, margin in rects:
            h = top - bottom
            target: _Line | None = None
            for line in page_lines:
                if abs(line.y - top) <= max(2.5, 0.45 * max(line._height, h)):
                    target = line
                    break
            if target is None:
                target = _Line(page=pno + 1, y=top)
                page_lines.append(target)
            target.parts.append((left, right, text))
            target._height = max(target._height, h)
            target.margin = target.margin or margin
        lines.extend(page_lines)
    return lines


def _body_height(lines: list[_Line]) -> float:
    weight: Counter[float] = Counter()
    for line in lines:
        weight[round(line._height * 2) / 2] += len(line.text())
    return weight.most_common(1)[0][0]


def _repeated_texts(lines: list[_Line], total_pages: int) -> set[str]:
    """跨页重复行（页眉/页脚）的归一化文本。"""
    pages_of: defaultdict[str, set[int]] = defaultdict(set)
    for line in lines:
        pages_of[_norm_key(line.text())].add(line.page)
    threshold = max(6, int(0.12 * total_pages))
    return {key for key, pages in pages_of.items() if len(pages) >= threshold}


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _heading_level(height: float, body: float) -> int:
    ratio = height / body if body else 0.0
    for min_ratio, level in _HEAD_RATIOS:
        if ratio >= min_ratio:
            return level
    return 0


def _is_heading_text(text: str) -> bool:
    return (
        len(text) <= _HEAD_MAX_LEN
        and not text.endswith(_HEAD_END_VETO)
        and not _TOC_ENTRY_RE.search(text)
    )


def _join_text(cur: str, nxt: str) -> str:
    """断词拼接：行尾连字符 + 下个词小写 → 直接相连。"""
    if cur.endswith("-") and nxt[:1].islower():
        return cur[:-1] + nxt
    return cur + " " + nxt


def _split_long(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    buf = ""
    for sentence in _SENT_SPLIT_RE.split(text):
        candidate = f"{buf} {sentence}".strip()
        if len(candidate) > limit and buf:
            out.append(buf)
            buf = sentence
        else:
            buf = candidate
    if buf:
        out.append(buf)
    final: list[str] = []
    for part in out:
        while len(part) > limit:
            cut = part.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            final.append(part[:cut])
            part = part[cut:].lstrip()
        if part:
            final.append(part)
    return final


def _assemble_chunks(lines: list[_Line], body: float) -> tuple[list[ChunkDraft], float, int]:
    """行 → 段落 → 组块；返回 (drafts, 表格页占比, 总页数)。"""
    body_left: Counter[float] = Counter()
    for line in lines:
        if abs(line._height - body) <= 0.6 and len(line.text()) > 20:
            body_left[round(line.x)] += 1
    column_left = body_left.most_common(1)[0][0] if body_left else 0

    total_pages = max((line.page for line in lines), default=0)
    repeated = _repeated_texts(lines, total_pages)

    paragraphs: list[tuple[str, int, tuple[str, ...], int]] = []
    stack: list[str] = []
    cur = ""
    cur_page = 0
    cur_head: tuple[str, ...] = ()
    para_no = 0
    prev: _Line | None = None

    def flush() -> None:
        nonlocal cur, para_no
        if len(cur.strip()) >= 2:
            paragraphs.append((cur.strip(), cur_page, cur_head, para_no))
            para_no += 1
        cur = ""

    for line in lines:
        text = line.text().strip()
        if not text:
            continue
        # 家具行过滤：边距区小字（页眉/页脚/索引页"1172 Index"）、纯页码、跨页重复行
        if line.margin and line._height <= body * 1.1:
            continue
        if _PAGE_NUM_RE.match(text) and line._height <= body * 0.85:
            continue
        if _norm_key(text) in repeated and line._height <= body * 1.02:
            continue

        level = _heading_level(line._height, body)
        if level and not _is_heading_text(text):
            level = 0  # 章节首行大字排版的句子 → 当正文
        if level:
            flush()
            stack = stack[: level - 1] + [text]
            prev = None
            continue

        new_para = False
        if not cur:
            new_para = True
        elif prev is not None:
            if line.page != prev.page:
                ends_sentence = prev.text().rstrip().endswith(
                    ("。", "．", ".", "！", "？", "!", "?", ":")
                )
                new_para = (line.x > column_left + 6) or ends_sentence
            else:
                gap = prev.y - line.y
                new_para = gap > prev._height * 1.6 or line.x > column_left + 6
        if new_para and cur:
            flush()
        if not cur:
            cur_page = line.page
            cur_head = tuple(stack)
        cur = _join_text(cur, text) if cur else text
        prev = line

    flush()

    chunks: list[ChunkDraft] = []
    buf = ""
    buf_page = 0
    buf_head: tuple[str, ...] = ()
    buf_para = 0

    def flush_chunk() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(
                ChunkDraft(
                    content=buf.strip(),
                    heading_path=" / ".join(buf_head) if buf_head else None,
                    page=buf_page or None,
                    chapter=buf_head[0] if buf_head else None,
                    paragraph=buf_para,
                )
            )
        buf = ""

    for text, page, head, pno in paragraphs:
        for part in _split_long(text, CHUNK_MAX):
            if buf and len(buf) + 1 + len(part) > CHUNK_MAX:
                flush_chunk()
            if not buf:
                buf_page, buf_head, buf_para = page, head, pno
            buf = _join_text(buf, part) if buf else part
    flush_chunk()

    if len(chunks) >= 2 and len(chunks[-1].content) < CHUNK_MIN_MERGE:
        tail = chunks.pop()
        chunks[-1].content = _join_text(chunks[-1].content, tail.content)

    # 表格页占比（列间隙行统计；保守，宁可漏报）
    rows_by_page: Counter[int] = Counter()
    for line in lines:
        if line.col_row_gaps() >= 1:
            rows_by_page[line.page] += 1
    table_pages = sum(1 for cnt in rows_by_page.values() if cnt >= _TABLE_MIN_ROWS)
    table_ratio = (table_pages / total_pages) if total_pages else 0.0
    return chunks, round(table_ratio, 3), total_pages


def iter_pdf_fast(path: Path) -> Iterator[tuple[int, int, list[ChunkDraft], dict | None]]:
    """快通道解析（生成器协议与 parser.iter_parse_document 一致）。"""
    try:
        pdf = pdfium.PdfDocument(path)
    except Exception as exc:  # 损坏/加密
        raise UnparseableError(f"PDF 无法打开（损坏或加密？）：{exc}") from exc

    try:
        lines = _extract_lines(pdf)
    finally:
        pdf.close()

    total_text = sum(len(line.text()) for line in lines)
    if total_text < 20:
        raise UnparseableError("未提取到有效文本（疑似扫描版/无文本层）")

    body = _body_height(lines)
    drafts, table_ratio, pages = _assemble_chunks(lines, body)
    if not drafts:
        raise UnparseableError("未提取到可检索内容")

    meta = {"table_ratio": table_ratio, "pages": pages}
    yield (pages, pages, drafts, meta)
