"""资料端点（T014 上传 / T018 列表·下载·删除·重处理）。

契约见 specs/001-core-qa/contracts/api.md：
- POST   /api/documents            上传（sha256 判重 → 200 duplicate；无法解析仍 201）
- GET    /api/documents            列表：分页 + 搜索 + 排序（source=upload|browser，FR-009）
- GET    /api/documents/{id}/original  原文件下载（字节级保真，FR-013）
- POST   /api/documents/{id}/reprocess 重试解析
- DELETE /api/documents/{id}       级联删除 chunks + 原文件（FR-003/011）
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.ingestion.tasks import enqueue_ingestion
from app.models import Chunk, Document, DocumentStatus, SourceType, User
from app.storage import get_blob_store
from app.textmatch import like_pattern, make_snippet

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


_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*(页|块)")


def _doc_dict(doc: Document) -> dict:
    # 结构化进度（进度条用）：从进度文案提取，如"解析中 300/1240 页"、"索引中 64/3046 块"
    progress = None
    if doc.status is DocumentStatus.processing and doc.status_reason:
        match = _PROGRESS_RE.search(doc.status_reason)
        if match:
            progress = {
                "done": int(match.group(1)),
                "total": int(match.group(2)),
                "unit": match.group(3),
            }
    data = {
        "id": str(doc.id),
        "name": doc.name,
        "format": doc.format,
        "size": doc.size_bytes,
        "status": doc.status.value,
        "status_reason": doc.status_reason,
        "progress": progress,
        "parse_hint": doc.parse_hint,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
    if doc.source_type is SourceType.browser:  # F2：网页来源附加字段
        data.update(
            {
                "source_url": doc.source_url,
                "site_name": doc.site_name,
                "first_captured_at": doc.first_captured_at.isoformat() if doc.first_captured_at else None,
                "last_captured_at": doc.last_captured_at.isoformat() if doc.last_captured_at else None,
                "visit_count": doc.visit_count,
                "snapshot": {"state": doc.snapshot_state or "none", "bytes": doc.snapshot_bytes},
            }
        )
    return data


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


# ── 列表：分页 + 搜索 + 排序（2026-10-02 列表增强）──
# 排序白名单：字段名 → 表达式（防注入；前缀 `-` 表示倒序）
_UPLOAD_SORTS: dict[str, object] = {
    "created_at": Document.created_at,
    "name": sa.func.lower(Document.name),
    "size": Document.size_bytes,
}
_BROWSER_SORTS: dict[str, object] = {
    "last_captured_at": Document.last_captured_at,
    "first_captured_at": Document.first_captured_at,
    "visit_count": Document.visit_count,
    "name": sa.func.lower(Document.name),
    "size": Document.size_bytes,
}
_DEFAULT_SORT = {"upload": "-created_at", "browser": "-last_captured_at"}
_MAX_PAGE_SIZE = 100


@router.get("")
async def list_documents(
    source: str = "upload",
    q: str = "",
    sort: str = "",
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """source=upload（缺省，F1）| browser（F2；conversation 不列表）。

    - q：标题/站点/网址 + 正文分块子串匹配（chunks.content ILIKE，pg_trgm GIN 加速）；
      命中正文时返回 match={"type":"content","snippet":"…"}，标题/网址命中 type 为 name/url。
    - sort：白名单字段，`-` 前缀倒序；默认 上传=上传时间↓ / 浏览=最近浏览时间↓。
    - 返回 {items,total,page,page_size}；page/page_size 越界钳制到有效范围。
    """
    if source not in {"upload", "browser"}:
        raise HTTPException(status_code=400, detail="source 仅支持 upload / browser")
    source_type = SourceType.browser if source == "browser" else SourceType.upload
    sorts = _BROWSER_SORTS if source_type is SourceType.browser else _UPLOAD_SORTS

    sort = sort or _DEFAULT_SORT[source]
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    if field not in sorts:
        raise HTTPException(
            status_code=400,
            detail=f"sort 仅支持 {' / '.join(sorts)}（前缀 - 表示倒序）",
        )

    conditions: list = [
        Document.owner_user_id == user.id,
        Document.source_type == source_type,
    ]
    q = q.strip()
    pattern = like_pattern(q) if q else None
    if pattern:
        text_conds = [Document.name.ilike(pattern, escape="\\")]
        if source_type is SourceType.browser:
            text_conds.append(Document.source_url.ilike(pattern, escape="\\"))
            text_conds.append(Document.site_name.ilike(pattern, escape="\\"))
        text_conds.append(
            select(Chunk.id)
            .where(
                Chunk.document_id == Document.id,
                Chunk.content.ilike(pattern, escape="\\"),
            )
            .exists()
        )
        conditions.append(sa.or_(*text_conds))

    page_size = max(1, min(page_size, _MAX_PAGE_SIZE))
    total = int(
        await session.scalar(
            select(sa.func.count()).select_from(Document).where(*conditions)
        )
        or 0
    )
    total_pages = max(1, -(-total // page_size))
    page = min(max(page, 1), total_pages)

    column = sorts[field]
    primary = sa.nulls_last(column.desc() if desc else column.asc())
    tie = Document.id.desc() if desc else Document.id.asc()
    rows = (
        await session.scalars(
            select(Document)
            .where(*conditions)
            .order_by(primary, tie)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    if not pattern:
        items = [_doc_dict(doc) for doc in rows]
    else:
        q_lower = q.lower()
        flagged: list[tuple] = []
        content_need: list[uuid.UUID] = []
        for doc in rows:
            name_hit = q_lower in doc.name.lower()
            url_hit = source_type is SourceType.browser and (
                q_lower in (doc.source_url or "").lower()
                or q_lower in (doc.site_name or "").lower()
            )
            flagged.append((doc, name_hit, url_hit))
            if not name_hit and not url_hit:
                content_need.append(doc.id)
        snippets: dict[uuid.UUID, str] = {}
        if content_need:
            chunk_rows = (
                await session.execute(
                    select(Chunk.document_id, Chunk.content)
                    .where(
                        Chunk.document_id.in_(content_need),
                        Chunk.content.ilike(pattern, escape="\\"),
                    )
                    .order_by(Chunk.created_at)
                )
            ).all()
            for doc_id, content in chunk_rows:
                snippets.setdefault(doc_id, content)
        items = []
        for doc, name_hit, url_hit in flagged:
            data = _doc_dict(doc)
            if name_hit:
                data["match"] = {"type": "name", "snippet": None}
            elif url_hit:
                data["match"] = {"type": "url", "snippet": None}
            else:
                content = snippets.get(doc.id)
                data["match"] = {
                    "type": "content",
                    "snippet": make_snippet(content, q) if content else None,
                }
            items.append(data)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    doc = await _get_owned_document(session, user, document_id)
    return _doc_dict(doc)


# 可安全内联浏览的格式（FR-015）；其余格式一律 attachment（防同源 XSS）
_INLINE_FORMATS = {"pdf", "epub", "txt", "md", "markdown"}


@router.get("/{document_id}/original")
async def download_original(
    document_id: uuid.UUID,
    inline: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    doc = await _get_owned_document(session, user, document_id)
    path = get_blob_store().path(doc.original_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="原文件已不存在")
    media_type = mimetypes.guess_type(doc.name)[0] or "application/octet-stream"
    disposition = "inline" if (inline and doc.format in _INLINE_FORMATS) else "attachment"
    return FileResponse(
        path, filename=doc.name, media_type=media_type, content_disposition_type=disposition
    )


@router.post("/{document_id}/reprocess")
async def reprocess(
    document_id: uuid.UUID,
    mode: str = "auto",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """重试解析；mode=deep 时 PDF 走 Docling 分页批处理（表格/版面更完整，较慢，R7）。"""
    if mode not in {"auto", "deep"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 auto / deep")
    doc = await _get_owned_document(session, user, document_id)
    doc.status = DocumentStatus.processing
    doc.status_reason = None
    doc.parse_hint = None
    await session.commit()
    enqueue_ingestion(doc.id, mode)
    return {"id": str(doc.id), "status": "processing", "mode": mode}


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


# 快照回放：CSP sandbox + gzip 直出（F2 research R4；防归档页成为攻击面）
_SNAPSHOT_CSP = (
    "sandbox; default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; media-src data:; frame-ancestors 'self'; "
    "base-uri 'none'; form-action 'none'"
)


@router.get("/{document_id}/snapshot")
async def get_snapshot(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """浏览器来源的页面快照（前端以 `<iframe sandbox=\"\">` 嵌入）。"""
    doc = await _get_owned_document(session, user, document_id)
    if doc.snapshot_state != "kept" or not doc.snapshot_path:
        raise HTTPException(status_code=404, detail="该条目没有快照")
    path = get_blob_store().path(doc.snapshot_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="快照文件已不存在")
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Encoding": "gzip",  # 文件即 gzip 字节，原样直出
            "Content-Security-Policy": _SNAPSHOT_CSP,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("", status_code=200)
async def cleanup_documents(
    source: str = "",
    before: datetime | None = None,
    after: datetime | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """按时间范围批量清理（F2 FR-007）：必须显式 source=browser，至少一个时间界。"""
    if source != "browser":
        raise HTTPException(status_code=400, detail="批量清理必须显式 source=browser")
    if before is None and after is None:
        raise HTTPException(status_code=400, detail="至少提供 before 或 after 之一")
    conditions = [
        Document.owner_user_id == user.id,
        Document.source_type == SourceType.browser,
    ]
    if after is not None:
        conditions.append(Document.last_captured_at >= after)
    if before is not None:
        conditions.append(Document.last_captured_at < before)
    docs = (await session.scalars(select(Document).where(*conditions))).all()
    for doc in docs:
        await run_in_threadpool(get_blob_store().delete_document_dir, str(user.id), str(doc.id))
        await session.delete(doc)  # chunks 由 FK CASCADE 清理
    await session.commit()
    return {"deleted": len(docs)}
