"""Docling 解析管线（T015）：格式分派 → 结构化分块；无法解析判定（FR-014）。

判定规则（spec FR-014）：无文本层 / 格式不支持 / 损坏或加密 → UnparseableError
（由管线登记为 unparseable 状态并保留原文件，不丢弃）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Docling 首次运行需下载模型；国内网络走 HuggingFace 镜像（须在导入 docling 前设置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

DOCLING_FORMATS = {
    "pdf", "epub", "docx", "html", "htm", "md", "markdown",
    "pptx", "xlsx", "adoc", "asciidoc", "csv",
}
TEXT_FORMATS = {"txt"}


class UnparseableError(Exception):
    """无法解析（FR-014）：文件损坏/加密/不支持的格式 —— 文件仍会保存登记，仅内容不可读。"""


class ParseInfraError(Exception):
    """解析依赖不可用（网络中断、模型下载失败等）—— 属环境问题，可重试。"""


# 网络/环境类错误的特征词（用于区分"可重试"与"无法解析"）
_INFRA_HINTS = (
    "Server disconnected",
    "Connection",
    "ConnectError",
    "RemoteProtocolError",
    "ReadTimeout",
    "Timeout",
    "timed out",
    "SSL",
    "Could not connect",
    "Failed to download",
    "huggingface",
    "hf-mirror",
)


def _classify_parse_error(exc: Exception) -> Exception:
    message = str(exc)
    if any(hint in message for hint in _INFRA_HINTS):
        return ParseInfraError(f"解析依赖不可用（网络/环境），可重试：{message}")
    return UnparseableError(f"解析失败（文件损坏或受保护？）：{message}")


@dataclass
class ChunkDraft:
    content: str
    heading_path: str | None = None
    page: int | None = None
    chapter: str | None = None
    paragraph: int | None = None


def _first_page_no(chunk) -> int | None:
    """提取 chunk 的首页码；元数据缺失（纯文本/表格等）返回 None。"""
    try:
        return int(chunk.meta.doc_items[0].prov[0].page_no)
    except (AttributeError, IndexError, TypeError):
        return None


def parse_document(path: Path, fmt: str) -> list[ChunkDraft]:
    """同步解析（由调用方放入 threadpool，避免阻塞事件循环）。"""
    if not path.exists():
        raise UnparseableError("原文件不存在")
    if fmt in TEXT_FORMATS:
        return _parse_text(path)
    if fmt not in DOCLING_FORMATS:
        raise UnparseableError(f"暂不支持解析的格式：.{fmt}（文件已保存，可下载）")
    return _parse_with_docling(path, fmt)


def _parse_text(path: Path) -> list[ChunkDraft]:
    text = path.read_text(encoding="utf-8", errors="replace")
    drafts = [
        ChunkDraft(content=para.strip(), paragraph=index)
        for index, para in enumerate(p for p in text.split("\n\n") if p.strip())
    ]
    if not drafts:
        raise UnparseableError("空文件或无有效文本")
    return drafts


def _parse_with_docling(path: Path, fmt: str) -> list[ChunkDraft]:
    try:
        from docling.chunking import HierarchicalChunker
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise ParseInfraError(f"解析器不可用：{exc}") from exc

    try:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        document = result.document
    except Exception as exc:  # 损坏/加密 → Unparseable；网络/模型下载 → ParseInfra（可重试）
        raise _classify_parse_error(exc) from exc

    markdown = document.export_to_markdown()
    if len(markdown.strip()) < 20:
        hint = "（疑似扫描版/无文本层）" if fmt == "pdf" else ""
        raise UnparseableError(f"未提取到有效文本{hint}")

    chunker = HierarchicalChunker()
    drafts: list[ChunkDraft] = []
    for chunk in chunker.chunk(document):
        content = chunk.text.strip()
        if not content:
            continue
        headings: list[str] = list(getattr(chunk.meta, "headings", None) or [])
        page_no = _first_page_no(chunk)
        drafts.append(
            ChunkDraft(
                content=content,
                heading_path=" / ".join(headings) or None,
                page=page_no,
                chapter=headings[-1] if headings else None,
            )
        )
    if not drafts:
        raise UnparseableError("未提取到可检索内容")
    return drafts
