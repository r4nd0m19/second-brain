"""笔记写入（MCP「写入回存」）：资料级文档，走标准解析/入库管线（与上传同链路）。

source_type=note：可被检索/问答引用（orchestrator 以「笔记」标注）；
不出现在资料列表（与对话回写同管理边界），不带 conversation 归属。
"""

from __future__ import annotations

import io
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.ingestion.tasks import enqueue_ingestion
from app.models import Document, DocumentStatus, SourceType
from app.storage import get_blob_store


async def save_note(
    session: AsyncSession,
    owner_id: uuid.UUID,
    title: str,
    content: str,
    source: str = "",
) -> dict:
    """写入一条笔记 → 后台解析入库（返回 {id, status}）。"""
    doc_id = uuid.uuid4()
    body = f"> 来源：{source}\n\n{content}" if source else content
    store = get_blob_store()
    rel, digest, size = await run_in_threadpool(
        store.save, str(owner_id), str(doc_id), "content.md", io.BytesIO(body.encode("utf-8"))
    )
    doc = Document(
        id=doc_id,
        owner_user_id=owner_id,
        name=(title.strip() or "未命名笔记")[:200],
        format="md",
        size_bytes=size,
        sha256=digest,
        status=DocumentStatus.processing,
        source_type=SourceType.note,
        original_path=rel,
    )
    session.add(doc)
    await session.commit()
    enqueue_ingestion(doc.id)
    return {"id": str(doc.id), "status": doc.status.value}
