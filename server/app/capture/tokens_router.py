"""采集凭据管理端点（F2，会话认证）：列表 / 创建（明文仅一次）/ 吊销。

契约见 specs/002-browser-capture/contracts/capture-api.md。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.capture.security import generate_token
from app.db import get_session
from app.models import CaptureToken, User

router = APIRouter(prefix="/api/capture/tokens", tags=["capture-tokens"])


_ALLOWED_SCOPES = {"capture", "read", "write"}  # capture=采集写入；read=只读；write=只读+写入回存


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scope: str = Field(default="capture")


def _token_dict(row: CaptureToken) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "prefix": row.prefix,
        "scope": row.scope,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


@router.get("")
async def list_tokens(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[dict]:
    rows = (
        await session.scalars(
            select(CaptureToken)
            .where(CaptureToken.owner_user_id == user.id)
            .order_by(CaptureToken.created_at.desc())
        )
    ).all()
    return [_token_dict(row) for row in rows]


@router.post("", status_code=201)
async def create_token(
    payload: TokenCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if payload.scope not in _ALLOWED_SCOPES:
        raise HTTPException(status_code=400, detail="scope 仅支持 capture / read / write")
    plain, prefix, digest = generate_token()
    row = CaptureToken(
        owner_user_id=user.id,
        name=payload.name,
        prefix=prefix,
        token_hash=digest,
        scope=payload.scope,
    )
    session.add(row)
    await session.flush()
    result = {"id": str(row.id), "name": row.name, "prefix": row.prefix, "token": plain}
    await session.commit()
    return result


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    purge: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """缺省 = 吊销（立即失效、保留记录）；`?purge=1` = 彻底删除（仅限已吊销，防误删）。"""
    row = await session.scalar(
        select(CaptureToken).where(
            CaptureToken.id == token_id, CaptureToken.owner_user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="凭据不存在")
    if purge:
        if row.revoked_at is None:
            raise HTTPException(
                status_code=409, detail="仅可彻底删除已吊销的凭据（请先吊销）"
            )
        await session.delete(row)
        await session.commit()
        return
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
