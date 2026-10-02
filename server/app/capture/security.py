"""采集凭据：生成与校验（F2 research R2；OWASP 实践：只存哈希、show once、可吊销）。

明文 token 形如 `sb_cap_<43字符 base64url>`；服务端仅存 sha256 + 展示前缀。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CaptureToken

TOKEN_PREFIX = "sb_cap_"
_PREFIX_DISPLAY_LEN = len(TOKEN_PREFIX) + 8  # 展示前缀 = sb_cap_ + 8 字符
LAST_USED_THROTTLE_SECONDS = 60  # last_used_at 节流写（避免每请求一次 UPDATE）


class CaptureTokenError(Exception):
    """凭据校验失败；kind ∈ {invalid, scope}（映射 401 / 403）。"""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def generate_token() -> tuple[str, str, str]:
    """生成 (明文 token, 展示前缀, sha256 十六进制)；明文仅在创建响应中返回一次。"""
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return token, token[:_PREFIX_DISPLAY_LEN], hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _load_valid_token(session: AsyncSession, raw_token: str) -> CaptureToken:
    """哈希匹配 + 未吊销；失败抛 invalid。"""
    row = await session.scalar(
        select(CaptureToken).where(CaptureToken.token_hash == hash_token(raw_token))
    )
    if row is None or row.revoked_at is not None:
        raise CaptureTokenError("invalid", "凭据无效或已吊销")
    return row


async def _touch_last_used(session: AsyncSession, row: CaptureToken) -> None:
    now = datetime.now(timezone.utc)
    if row.last_used_at is None or now - row.last_used_at > timedelta(
        seconds=LAST_USED_THROTTLE_SECONDS
    ):
        row.last_used_at = now
        await session.commit()


async def verify_capture_token(session: AsyncSession, raw_token: str) -> CaptureToken:
    """采集端点：哈希匹配 + 未吊销 + scope=capture；通过后节流更新 last_used_at。"""
    row = await _load_valid_token(session, raw_token)
    if row.scope != "capture":
        raise CaptureTokenError("scope", "凭据 scope 不符（需要 capture）")
    await _touch_last_used(session, row)
    return row


async def verify_scoped_token(
    session: AsyncSession, raw_token: str, allowed_scopes: set[str]
) -> CaptureToken:
    """通用 Bearer 端点（MCP）：哈希匹配 + 未吊销 + scope ∈ allowed_scopes。"""
    row = await _load_valid_token(session, raw_token)
    if row.scope not in allowed_scopes:
        raise CaptureTokenError(
            "scope", f"凭据 scope 不符（需要 {'/'.join(sorted(allowed_scopes))}）"
        )
    await _touch_last_used(session, row)
    return row
