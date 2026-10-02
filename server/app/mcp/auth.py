"""MCP 端点鉴权（ASGI 包装）：Bearer 凭据（scope ∈ {read, write}）+ 请求级上下文。

- 401 由本层直接返回（不带 WWW-Authenticate，避免客户端触发 OAuth 发现流程）；
- 校验通过后把 {scope, owner_user_id} 放进 ContextVar，工具层读取
  （write 工具在此之上二次把关 scope）。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from app.capture.security import CaptureTokenError, verify_scoped_token
from app.db import SessionLocal

# 请求级上下文：MCP 工具读取（ASGI 请求任务树内传播）
current_mcp_scope: ContextVar[str] = ContextVar("mcp_scope", default="")
current_mcp_owner: ContextVar[uuid.UUID | None] = ContextVar("mcp_owner", default=None)

_UNAUTHORIZED_BODY = (
    '{"error":"unauthorized","detail":"MCP 需要 Bearer 凭据（scope=read/write）"}'
).encode("utf-8")


class MCPAuthMiddleware:
    """校验 Authorization: Bearer sb_cap_...（scope read 或 write）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""

        row = None
        if token:
            async with SessionLocal() as session:
                try:
                    row = await verify_scoped_token(session, token, {"read", "write"})
                except CaptureTokenError:
                    row = None

        if row is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})
            return

        scope_reset = current_mcp_scope.set(row.scope)
        owner_reset = current_mcp_owner.set(row.owner_user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_mcp_scope.reset(scope_reset)
            current_mcp_owner.reset(owner_reset)
