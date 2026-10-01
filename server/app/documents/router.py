"""资料端点（T014 上传 / T018 列表·下载·删除·重处理）。

契约见 specs/001-core-qa/contracts/api.md：
- POST   /api/documents            上传（sha256 判重 → 200 duplicate；无法解析仍 201）
- GET    /api/documents            列表（**仅 source_type=upload**，FR-009）
- GET    /api/documents/{id}/original  原文件下载（字节级保真，FR-013）
- POST   /api/documents/{id}/reprocess 重试解析
- DELETE /api/documents/{id}       级联删除 chunks + 原文件（FR-003/011）
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.ingestion.tasks import enqueue_ingestion
from app.models import Document, DocumentStatus, SourceType, User
from app.storage import get_blob_store

router = APIRouter(prefix="/api/documents", tags=["documents"])


async def _get_owned_document(
    session: AsyncSession, user: User, document_id: uuid.UUID
) -> Document:
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_user_id == user.id
        )
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return doc


def _doc_dict(doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "name": doc.name,
        "format": doc.format,
        "size": doc.size_bytes,
        "status": doc.status.value,
        "status_reason": doc.status_reason,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    doc_id = uuid.uuid4()
    owner = str(user.id)
    filename = file.filename or "file"
    store = get_blob_store()

    rel_path, digest, size = await run_in_threadpool(
        store.save, owner, str(doc_id), filename, file.file
    )

    if size > settings.max_upload_mb * 1024 * 1024:
        store.delete_document_dir(owner, str(doc_id))
        raise HTTPException(
            status_code=413, detail=f"文件超过上限（{settings.max_upload_mb}MB）"
        )
    if size == 0:
        store.delete_document_dir(owner, str(doc_id))
        raise HTTPException(status_code=400, detail="空文件，已拒绝（未登记）")

    existing = await session.scalar(
        select(Document).where(
            Document.owner_user_id == user.id, Document.sha256 == digest
        )
    )
    if existing is not None:
        store.delete_document_dir(owner, str(doc_id))
        return JSONResponse(
            status_code=200,
            content={"duplicate": True, "existing_id": str(existing.id)},
        )

    fmt = Path(filename).suffix.lower().lstrip(".") or "unknown"
    doc = Document(
        id=doc_id,
        owner_user_id=user.id,
        name=filename,
        format=fmt,
        size_bytes=size,
        sha256=digest,
        status=DocumentStatus.processing,
        source_type=SourceType.upload,
        original_path=rel_path,
    )
    session.add(doc)
    await session.commit()

    enqueue_ingestion(doc.id)  # 后台解析入库（不阻塞上传响应）
    return {"id": str(doc.id), "status": doc.status.value}


@router.get("")
async def list_documents(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(Document)
            .where(
                Document.owner_user_id == user.id,
                Document.source_type == SourceType.upload,  # FR-009：仅上传来源
            )
            .order_by(Document.created_at.desc())
        )
    ).all()
    return [_doc_dict(doc) for doc in rows]


@router.get("/{document_id}/original")
async def download_original(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    doc = await _get_owned_document(session, user, document_id)
    path = get_blob_store().path(doc.original_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="原文件已不存在")
    media_type = mimetypes.guess_type(doc.name)[0] or "application/octet-stream"
    return FileResponse(path, filename=doc.name, media_type=media_type)


@router.post("/{document_id}/reprocess")
async def reprocess(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    doc = await _get_owned_document(session, user, document_id)
    doc.status = DocumentStatus.processing
    doc.status_reason = None
    await session.commit()
    enqueue_ingestion(doc.id)
    return {"id": str(doc.id), "status": "processing"}


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    doc = await _get_owned_document(session, user, document_id)
    await run_in_threadpool(
        get_blob_store().delete_document_dir, str(user.id), str(doc.id)
    )
    await session.delete(doc)  # chunks 由 FK CASCADE 清理
    await session.commit()
