"""入库管线（T016）：解析 → 分块 → embedding → 落库；状态机流转（spec FR-002/014）。

- 幂等（spec NFR Reliability）：重试前清理旧 chunks，不产生重复内容
- 解析逐批推进：批次间更新进度（status_reason）并让解析侧释放内存
  （2026-10-01 OOM 事故复盘，见 research.md R7）
- embedding 故障 → 停留 processing + 原因，可重试（reprocess）
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

from sqlalchemy import delete, update
from sqlalchemy.orm.exc import StaleDataError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import SessionLocal
from app.ingestion.embedding import EmbeddingError, get_embedding_provider
from app.ingestion.parser import ParseInfraError, UnparseableError, iter_parse_document
from app.ingestion.quality import is_indexable
from app.ingestion.webpage import chunk_markdown
from app.models import Chunk, Document, DocumentStatus, SourceType
from app.storage import get_blob_store

logger = logging.getLogger(__name__)


def _next_or_none(it: Iterator) -> object | None:
    """从解析生成器取下一批；正常结束返回 None（供 threadpool 调用）。"""
    try:
        return next(it)
    except StopIteration:
        return None


def _table_hint(meta: dict | None) -> str | None:
    """快通道表格占比超阈值 → 提示可深度解析（R7）。"""
    if not meta:
        return None
    ratio = float(meta.get("table_ratio") or 0.0)
    if ratio >= settings.table_hint_ratio:
        return (
            f"检测到较多表格（约 {ratio:.0%} 页面），表格结构可能不完整；"
            "可点「深度解析」用完整模型重解析（约 20 分钟）"
        )
    return None


async def _embed_and_store(session, doc: Document, drafts: list, meta: dict | None) -> None:
    """embedding + 落块（上传与网页来源共用）；进度写 status_reason（x/y 块）。"""
    # 非语言性垃圾块（SVG 坐标/CSS 数字海）不索引——防"假强命中"（R17 根治，2026-10-03）
    drafts = [d for d in drafts if is_indexable(d.content)]
    if not drafts:
        doc.status = DocumentStatus.indexed
        doc.status_reason = "正文无可索引文本（已过滤非语言性块）"
        logger.info("ingest junk-filtered (0 usable chunks): %s", doc.name)
        return
    total_blocks = len(drafts)
    doc.status_reason = f"索引中 0/{total_blocks} 块"
    await session.commit()

    async def _on_embed_progress(done_blocks: int, total_count: int) -> None:
        doc.status_reason = f"索引中 {done_blocks}/{total_count} 块"
        await session.commit()

    vectors = await get_embedding_provider().embed(
        [d.content for d in drafts], on_progress=_on_embed_progress
    )

    for draft, vector in zip(drafts, vectors, strict=True):
        session.add(
            Chunk(
                document_id=doc.id,
                owner_user_id=doc.owner_user_id,
                content=draft.content,
                heading_path=draft.heading_path,
                page=draft.page,
                chapter=draft.chapter,
                paragraph=draft.paragraph,
                embedding=vector,
            )
        )
    doc.status = DocumentStatus.indexed
    doc.status_reason = None
    doc.parse_hint = _table_hint(meta)
    logger.info("ingest ok: %s chunks=%d", doc.name, len(drafts))


async def _ingest_webpage(session, doc: Document) -> None:
    """网页来源入库（F2）：content.md → Markdown 分块 → embedding；无正文时仅元信息。"""
    path = get_blob_store().path(doc.original_path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    drafts = chunk_markdown(text)
    if not drafts:
        # 仅元信息条目（spec Edge Case）：无正文可索引，直接 indexed（0 chunks）
        doc.status = DocumentStatus.indexed
        doc.status_reason = "仅元信息（无正文可索引）"
        logger.info("ingest browser metadata-only: %s", doc.name)
        return
    await _embed_and_store(session, doc, drafts, None)


async def ingest_document(document_id: uuid.UUID, mode: str = "auto") -> None:
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return

        try:
            # 幂等：清理旧内容块（重试/重入库不产生重复）
            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))

            if doc.source_type is SourceType.browser:
                # 网页来源（F2）：正文已由扩展提取为 content.md，免 Docling 解析
                await _ingest_webpage(session, doc)
                await session.commit()
                return

            path = get_blob_store().path(doc.original_path)
            gen = iter_parse_document(path, doc.format, mode)
            drafts = []
            meta: dict | None = None
            while True:
                item = await run_in_threadpool(_next_or_none, gen)
                if item is None:
                    break
                done, total, batch, batch_meta = item
                if batch:
                    drafts.extend(batch)
                if batch_meta is not None:
                    meta = batch_meta
                if total and doc.format == "pdf":
                    doc.status_reason = f"解析中 {done}/{total} 页"
                    await session.commit()

            if not drafts:
                raise UnparseableError("未提取到可检索内容")
            await _embed_and_store(session, doc, drafts, meta)

        except UnparseableError as exc:
            doc.status = DocumentStatus.unparseable
            doc.status_reason = str(exc)
            doc.parse_hint = None
            logger.info("ingest unparseable: %s reason=%s", doc.name, exc)

        except ParseInfraError as exc:
            doc.status = DocumentStatus.processing
            doc.status_reason = str(exc)
            logger.warning("ingest infra error (retryable): %s", exc)

        except EmbeddingError as exc:
            doc.status = DocumentStatus.processing
            doc.status_reason = f"embedding 服务失败，可重试：{exc}"
            logger.warning("ingest embedding error: %s", exc)

        except StaleDataError:
            # 文档在解析/嵌入期间被删除（如会话清理级联）——静默结束（2026-10-02 竞态实测）
            await session.rollback()
            logger.info("ingest skipped: 文档已删除 %s", document_id)
            return

        except Exception as exc:  # 未预期错误：保留可重试状态
            logger.exception("ingest unexpected error: %s", document_id)
            doc.status = DocumentStatus.processing
            doc.status_reason = f"未预期错误，可重试：{exc}"

        try:
            await session.commit()
        except StaleDataError:  # 状态更新期间文档被删除（同一竞态的收尾窗口）
            await session.rollback()
            logger.info("ingest skipped: 文档已删除 %s", document_id)


async def mark_interrupted_documents() -> None:
    """启动扫尾：上次进程中断（崩溃/重启）遗留的 processing 文档 → 标记可重试（R7）。

    不自动重跑（当年 OOM 会连锁崩溃），由用户在界面点「重试」显式触发。
    """
    async with SessionLocal() as session:
        result = await session.execute(
            update(Document)
            .where(Document.status == DocumentStatus.processing)
            .values(status_reason="上次解析被中断（服务重启/崩溃），点「重试」重新解析")
        )
        await session.commit()
        if result.rowcount:
            logger.warning("marked %d interrupted document(s) as retryable", result.rowcount)
