"""入库管线（T016）：解析 → 分块 → embedding → 落库；状态机流转（spec FR-002/014）。

- 幂等（spec NFR Reliability）：重试前清理旧 chunks，不产生重复内容
- embedding 故障 → 停留 processing + 原因，可重试（reprocess）
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete
from starlette.concurrency import run_in_threadpool

from app.db import SessionLocal
from app.ingestion.embedding import EmbeddingError, get_embedding_provider
from app.ingestion.parser import ParseInfraError, UnparseableError, parse_document
from app.models import Chunk, Document, DocumentStatus
from app.storage import get_blob_store

logger = logging.getLogger(__name__)


async def ingest_document(document_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return

        try:
            # 幂等：清理旧内容块（重试/重入库不产生重复）
            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))

            path = get_blob_store().path(doc.original_path)
            drafts = await run_in_threadpool(parse_document, path, doc.format)
            vectors = await get_embedding_provider().embed([d.content for d in drafts])

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
            logger.info("ingest ok: %s chunks=%d", doc.name, len(drafts))

        except UnparseableError as exc:
            doc.status = DocumentStatus.unparseable
            doc.status_reason = str(exc)
            logger.info("ingest unparseable: %s reason=%s", doc.name, exc)

        except ParseInfraError as exc:
            doc.status = DocumentStatus.processing
            doc.status_reason = str(exc)
            logger.warning("ingest infra error (retryable): %s", exc)

        except EmbeddingError as exc:
            doc.status = DocumentStatus.processing
            doc.status_reason = f"embedding 服务失败，可重试：{exc}"
            logger.warning("ingest embedding error: %s", exc)

        except Exception as exc:  # 未预期错误：保留可重试状态
            logger.exception("ingest unexpected error: %s", document_id)
            doc.status = DocumentStatus.processing
            doc.status_reason = f"未预期错误，可重试：{exc}"

        await session.commit()
