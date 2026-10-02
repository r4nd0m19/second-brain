"""采集接收端点（F2）：POST /api/capture/pages、GET /api/capture/ping（Bearer 认证）。

契约见 specs/002-browser-capture/contracts/capture-api.md：
- multipart 字段与 SingleFile 官方扩展 REST 上传对齐（url/file/title/captured_at/text/capture_id）
- 三分支：新建 201 / capture_id 幂等 200 duplicate / 同 URL 更新 200 updated
- 快照超限降级 skipped_oversize（不阻塞入库）；正文变化触发重分块 + 嵌入（异步）
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.capture.deps import require_capture_token
from app.capture.ratelimit import capture_limiter
from app.config import settings
from app.db import get_session
from app.ingestion.tasks import enqueue_ingestion
from app.models import CaptureToken, Document, DocumentStatus, SourceType
from app.storage import get_blob_store

router = APIRouter(prefix="/api/capture", tags=["capture"])

SERVER_VERSION = "0.1.0"


def normalize_url(raw: str) -> str:
    """URL 规范化：仅 http(s)、host 小写、去 fragment、保留 query（data-model.md）。"""
    parts = urlsplit(raw.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("仅支持 http(s) 页面 URL")
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _parse_captured_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="captured_at 需为 ISO8601") from exc
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="capture_id 需为 UUID") from exc


@router.post("/pages", status_code=201)
async def capture_page(
    request: Request,
    url: str = Form(...),
    title: str | None = Form(None),
    text: str | None = Form(None),
    captured_at: str | None = Form(None),
    capture_id: str | None = Form(None),
    file: UploadFile | None = File(None),
    token: CaptureToken = Depends(require_capture_token),
    session: AsyncSession = Depends(get_session),
):
    retry_after = capture_limiter.check_and_record(f"capture:{token.id}")
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="采集请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    ceiling = settings.capture_max_request_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > ceiling:
        raise HTTPException(
            status_code=413, detail=f"请求体超过上限（{settings.capture_max_request_mb}MB）"
        )

    try:
        normalized = normalize_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 缺 file 且无 text → 合法的"仅元信息条目"（spec Edge Case：正文提取失败时保留标题/URL）

    captured = _parse_captured_at(captured_at)
    capture_uuid = _parse_uuid(capture_id)
    host = urlsplit(normalized).netloc

    existing = await session.scalar(
        select(Document).where(
            Document.owner_user_id == token.owner_user_id,
            Document.source_type == SourceType.browser,
            Document.source_url == normalized,
        )
    )
    if existing is not None and capture_uuid is not None and existing.capture_id == capture_uuid:
        # 幂等重放：不更新计数、不重复入库
        return JSONResponse(status_code=200, content={"id": str(existing.id), "duplicate": True})

    store = get_blob_store()
    owner = str(token.owner_user_id)
    created = existing is None

    if created:
        doc = Document(
            id=uuid.uuid4(),
            owner_user_id=token.owner_user_id,
            name=title or normalized,
            format="html",
            size_bytes=0,
            sha256="",
            status=DocumentStatus.processing,
            source_type=SourceType.browser,
            original_path="",
            source_url=normalized,
            site_name=host,
            first_captured_at=captured,
            last_captured_at=captured,
            visit_count=1,
            capture_id=capture_uuid,
        )
    else:
        doc = existing
        doc.last_captured_at = captured
        doc.visit_count = (doc.visit_count or 0) + 1
        if capture_uuid is not None:
            doc.capture_id = capture_uuid
        if title:
            doc.name = title

    # 正文：写 content.md（先写文件、后提交 DB）；hash 变化 → 标记重嵌入
    # 空串视为"本次未提取到正文"：不覆盖既有正文，新建时按仅元信息处理
    need_index = False
    if text:
        rel, digest, size = store.save(
            owner, str(doc.id), "content.md", io.BytesIO(text.encode("utf-8"))
        )
        need_index = digest != doc.sha256
        doc.original_path = rel
        doc.sha256 = digest
        doc.size_bytes = size
        if need_index:
            doc.status = DocumentStatus.processing
            doc.status_reason = None
    elif created:
        rel, digest, size = store.save(owner, str(doc.id), "content.md", io.BytesIO(b""))
        doc.original_path = rel
        doc.sha256 = digest
        doc.size_bytes = 0

    # 快照：超限降级为仅正文+元信息（FR-014）
    if file is not None:
        limit = settings.capture_max_snapshot_mb * 1024 * 1024
        if file.size is not None and file.size > limit:
            if doc.snapshot_path:
                store.delete(doc.snapshot_path)  # 覆盖更新时防旧快照错配
            doc.snapshot_path = None
            doc.snapshot_bytes = None
            doc.snapshot_state = "skipped_oversize"
        else:
            try:
                snapshot_rel, snapshot_size = store.save_snapshot(owner, str(doc.id), file.file)
                doc.snapshot_path = snapshot_rel
                doc.snapshot_bytes = snapshot_size
                doc.snapshot_state = "kept"
            except OSError:
                doc.snapshot_state = "skipped_error"

    if created:
        session.add(doc)
    await session.commit()

    if need_index:
        enqueue_ingestion(doc.id)  # 异步分块 + 嵌入（不阻塞采集响应）
    elif created:
        # 仅元信息条目（spec Edge Case）：无正文可索引
        doc.status = DocumentStatus.indexed
        doc.status_reason = "仅元信息（无正文可索引）"
        await session.commit()

    snapshot_state = doc.snapshot_state or "none"
    if created:
        return JSONResponse(
            status_code=201,
            content={"id": str(doc.id), "duplicate": False, "snapshot": snapshot_state},
        )
    return JSONResponse(
        status_code=200,
        content={
            "id": str(doc.id),
            "updated": True,
            "reindexed": need_index,
            "snapshot": snapshot_state,
        },
    )


@router.get("/ping")
async def ping(token: CaptureToken = Depends(require_capture_token)) -> dict:
    """扩展「保存并测试」：Bearer 有效性 + scope 探测（不消耗采集限速额度）。"""
    return {
        "ok": True,
        "owner": str(token.owner_user_id),
        "scope": token.scope,
        "server_version": SERVER_VERSION,
    }
