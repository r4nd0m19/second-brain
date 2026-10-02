"""采集端点认证依赖：解析 Authorization: Bearer → 校验（401 无效/吊销，403 scope 不符）。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.capture.security import CaptureTokenError, verify_capture_token
from app.db import get_session
from app.models import CaptureToken


async def require_capture_token(
    request: Request, session: AsyncSession = Depends(get_session)
) -> CaptureToken:
    header = request.headers.get("authorization", "")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise HTTPException(
            status_code=401,
            detail="缺少采集凭据（Authorization: Bearer sb_cap_…）",
        )
    try:
        return await verify_capture_token(session, raw.strip())
    except CaptureTokenError as exc:
        raise HTTPException(
            status_code=401 if exc.kind == "invalid" else 403, detail=exc.detail
        ) from exc
