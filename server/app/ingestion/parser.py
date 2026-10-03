"""Docling 解析管线（T015）+ PDF 文本层快通道（T041）：格式分派 → 结构化分块；无法解析判定（FR-014）。

判定规则（spec FR-014）：无文本层 / 格式不支持 / 损坏或加密 → UnparseableError
（由管线登记为 unparseable 状态并保留原文件，不丢弃）。

解析模式（mode）：
- auto：PDF 走文本层快通道（pdf_fast：秒级、内存恒定）；其余格式走 Docling
  （无 ML 布局模型，本身很快）
- deep：PDF 走 Docling 分页批处理（保留表格/版面的 ML 结构；内存受控但慢，用户按需触发）

iter_parse_document 为生成器：逐批产出 (已解析页, 总页数, 本批 chunks, 最终 meta)。
批次间由调用方（pipeline）更新进度并释放内存（2026-10-01 OOM 事故复盘，见 research.md R7）。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Docling 首次运行需下载模型；国内网络走 HuggingFace 镜像（须在导入 docling 前设置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from app.config import settings

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


def iter_parse_document(
    path: Path, fmt: str, mode: str = "auto"
) -> Iterator[tuple[int, int, list[ChunkDraft], dict | None]]:
    """解析（生成器）。产出：(已解析页, 总页数, 本批 chunks, 最终 meta)。"""
    if not path.exists():
        raise UnparseableError("原文件不存在")
    if fmt in TEXT_FORMATS:
        yield (1, 1, _parse_text(path), None)
        return
    if fmt not in DOCLING_FORMATS:
        raise UnparseableError(f"暂不支持解析的格式：.{fmt}（文件已保存，可下载）")
    if fmt == "pdf" and mode != "deep" and settings.pdf_fast_parse:
        from app.ingestion.pdf_fast import iter_pdf_fast  # 延迟导入，避免循环依赖

        yield from iter_pdf_fast(path)
        return
    yield from _iter_docling(
        path, fmt, batch_pages=settings.parse_deep_page_batch if fmt == "pdf" else None
    )


def parse_document(path: Path, fmt: str) -> list[ChunkDraft]:
    """同步整体解析（向后兼容入口；由调用方放入 threadpool）。"""
    drafts: list[ChunkDraft] = []
    for _, _, batch, _meta in iter_parse_document(path, fmt):
        drafts.extend(batch)
    return drafts


def _parse_text(path: Path) -> list[ChunkDraft]:
    text = path.read_text(encoding="utf-8", errors="replace")
    drafts = [
        ChunkDraft(content=para.strip(), paragraph=index)
        for index, para in enumerate(p for p in text.split("\n\n") if p.strip())
    ]
    if not drafts:
        raise UnparseableError("空文件或无有效文本")
    return drafts


def _count_pdf_pages(path: Path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _chunk_document(document, chunker) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for chunk in chunker.chunk(document):
        content = chunk.text.strip()
        if not content:
            continue
        headings: list[str] = list(getattr(chunk.meta, "headings", None) or [])
        drafts.append(
            ChunkDraft(
                content=content,
                heading_path=" / ".join(headings) or None,
                page=_first_page_no(chunk),
                chapter=headings[-1] if headings else None,
            )
        )
    return drafts


def _build_docling_chunker():
    """HybridChunker（R5 决策）：按标题路径分块 + token 上限——防超长块超 embedding 输入上限。

    tokenizer 与 embedding 模型一致（bge-m3，XLM-R 系）；max_tokens=1024 ≈ 600-1000 中文字符，
    与网页/PDF 分块体量可比，远低于 bge-m3 的 8192 上限。
    （2026-10-03 范式审计整改：此前代码误用零参数 HierarchicalChunker、与 R5 记录不符。）
    """
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    return HybridChunker(
        tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=1024)
    )


def _iter_docling(
    path: Path, fmt: str, batch_pages: int | None
) -> Iterator[tuple[int, int, list[ChunkDraft], dict | None]]:
    """Docling 路径：非 PDF 整体解析；PDF 按页批解析（内存受控，R7）。"""
    try:
        from docling.document_converter import DocumentConverter

        chunker = _build_docling_chunker()
    except Exception as exc:  # 含 transformers/tokenizer 下载失败（网络）
        raise ParseInfraError(f"解析器不可用：{exc}") from exc
    try:
        if fmt != "pdf":
            result = DocumentConverter().convert(str(path))
            markdown = result.document.export_to_markdown()
            if len(markdown.strip()) < 20:
                raise UnparseableError("未提取到有效文本")
            drafts = _chunk_document(result.document, chunker)
            if not drafts:
                raise UnparseableError("未提取到可检索内容")
            yield (1, 1, drafts, None)
            return

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        options = PdfPipelineOptions()
        options.do_ocr = settings.parse_deep_do_ocr
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

        total = _count_pdf_pages(path)
        total_text = 0
        yielded = 0
        step = batch_pages or 120
        for start in range(1, total + 1, step):
            end = min(start + step - 1, total)
            result = converter.convert(str(path), page_range=(start, end))
            total_text += len(result.document.export_to_markdown().strip())
            drafts = _chunk_document(result.document, chunker)
            yielded += len(drafts)
            yield (end, total, drafts, None)
        if total_text < 20:
            raise UnparseableError("未提取到有效文本（疑似扫描版/无文本层）")
        if not yielded:
            raise UnparseableError("未提取到可检索内容")
    except (UnparseableError, ParseInfraError):
        raise
    except Exception as exc:  # 损坏/加密 → Unparseable；网络/模型下载 → ParseInfra（可重试）
        raise _classify_parse_error(exc) from exc
