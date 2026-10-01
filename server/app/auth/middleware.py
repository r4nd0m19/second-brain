"""全 API 认证守卫（constitution VII 底线 3：认证边界从第一天存在）。

规则：
- `/api/*` 全部需要有效会话，除 `/api/auth/login`
- 非 /api 路径（静态 PWA、/health）放行
"""

from starlette.responses import JSONResponse

from app.auth.security import COOKIE_NAME, read_session

_ALLOW_PATHS = {"/api/auth/login"}


class ApiAuthMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return

        if scope["path"] in _ALLOW_PATHS:
            await self.app(scope, receive, send)
            return

        token = self._session_token(scope)
        if read_session(token) is None:
            response = JSONResponse(
                {"error": {"code": "unauthorized", "message": "未登录"}}, status_code=401
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _session_token(scope) -> str | None:
        for name, value in scope["headers"]:
            if name == b"cookie":
                for part in value.decode("latin-1").split(";"):
                    key, _, raw = part.strip().partition("=")
                    if key == COOKIE_NAME:
                        return raw or None
        return None
