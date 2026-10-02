"""全 API 认证守卫（constitution VII 底线 3：认证边界从第一天存在）。

规则：
- `/api/*` 全部需要有效会话，除 `/api/auth/login`
- 采集 Bearer 端点（F2：`/api/capture/pages`、`/api/capture/ping`）由路由层
  `require_capture_token` 校验，不走会话守卫（扩展无 Cookie）
- 非 /api 路径（静态 PWA、/health）放行
"""

from starlette.responses import JSONResponse, Response

from app.auth.security import COOKIE_NAME, read_session

_ALLOW_PATHS = {"/api/auth/login"}

# 采集端点（F2）：会话守卫豁免，由 require_capture_token 做 Bearer 认证
_CAPTURE_BEARER_PATHS = {"/api/capture/pages", "/api/capture/ping"}


class ApiAuthMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return

        if scope["path"] in _ALLOW_PATHS or scope["path"] in _CAPTURE_BEARER_PATHS:
            # 开发期兜底：扩展 SW 声明 host_permissions 时不会发预检；
            # 若权限被撤销等导致转为普通跨域，给出最小预检响应（真实请求仍需 Bearer）。
            if scope["method"] == "OPTIONS" and scope["path"] in _CAPTURE_BEARER_PATHS:
                response = Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "POST, GET",
                        "Access-Control-Allow-Headers": "authorization, content-type",
                    },
                )
                await response(scope, receive, send)
                return
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
