"""MCP 服务端（Streamable HTTP，挂载于 /mcp）：Claude Code 等 harness 的接入面。

工具集（2026-10-02 定）：
- search_knowledge / get_document / search_conversations —— scope=read 即可；
- save_note（写入回存 → source_type=note，可被检索）—— 需 scope=write（单独 grant）。

鉴权与上下文见 auth.py；纯函数实现见 tools.py。
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Match, Mount, get_route_path

from app.config import settings
from app.db import SessionLocal
from app.mcp import tools
from app.mcp.auth import MCPAuthMiddleware, current_mcp_owner, current_mcp_scope
from app.notes import save_note as _save_note

mcp = MCPServer(
    "second-brain",
    instructions=(
        "用户的个人第二大脑：可检索他上传的资料、浏览过的网页、历史对话与笔记。"
        "当问题涉及他个人看过/学过/存过的内容时，先调用 search_knowledge 检索，再作答并给出来源。"
    ),
)


def _owner():
    owner = current_mcp_owner.get()
    if owner is None:  # 理论不可达（auth 层保证）；防御式
        raise RuntimeError("缺少凭据上下文")
    return owner


@mcp.tool(
    description="检索第二大脑：上传的资料、浏览过的网页、笔记（语义+关键词混合检索）。返回命中片段、出处与网页链接。"
)
async def search_knowledge(query: str, limit: int = 8) -> list[dict]:
    async with SessionLocal() as session:
        return await tools.search_knowledge(session, _owner(), query, limit)


@mcp.tool(
    description="按 document_id 读取第二大脑中文档的全文（长文截断）；配合 search_knowledge 的命中结果使用。"
)
async def get_document(document_id: str, max_chars: int = 20000) -> dict:
    async with SessionLocal() as session:
        return await tools.get_document(session, _owner(), document_id, max_chars)


@mcp.tool(description="搜索用户与第二大脑的历史对话内容（消息正文），返回会话级命中与片段。")
async def search_conversations(query: str, limit: int = 10) -> list[dict]:
    async with SessionLocal() as session:
        return await tools.search_conversations(session, _owner(), query, limit)


@mcp.tool(
    description="把一段笔记/结论写入第二大脑（之后可被检索引用）。需要 write 权限凭据；source 注明来源场景。"
)
async def save_note(title: str, content: str, source: str = "Claude Code (MCP)") -> dict:
    if current_mcp_scope.get() != "write":
        raise ToolError("需要写入权限：当前凭据 scope 为只读（read），请改用 write 凭据")
    async with SessionLocal() as session:
        return await _save_note(session, _owner(), title, content, source)


# DNS-rebinding 防护：默认仅放行本机（T093 审计：原实现硬编码某内网 IP——换网段失效且公开仓库
# 泄露作者网络信息）；局域网/自定义域名经 MCP_ALLOWED_HOSTS 环境变量追加（逗号分隔，含端口），
# 凭据鉴权始终为硬门槛
_DEFAULT_ALLOWED_HOSTS = ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000"]


def _allowed_hosts() -> list[str]:
    extra = [h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()]
    return _DEFAULT_ALLOWED_HOSTS + extra


def build_mcp_asgi_app():
    """构建挂载用 ASGI 应用（streamable HTTP，路径 /，鉴权包装在外层）。"""
    allowed = _allowed_hosts()
    app = mcp.streamable_http_app(
        streamable_http_path="/",
        json_response=True,  # 工具无流式进度：JSON 响应更利于调试与客户端解析
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed,
            allowed_origins=[f"http://{h}" for h in allowed]
            + [f"https://{h}" for h in allowed],
        ),
    )
    return MCPAuthMiddleware(app)


class ExactMount(Mount):
    """Mount 的精确路径变体：`/mcp`（无尾斜杠）与 `/mcp/...` 都 FULL 匹配。

    Starlette Mount 的 path_regex 只认 `{path}/...`，请求精确 `/mcp` 会漏给
    后面的 SPA 通配路由（表现为 405/307）。客户端（Claude Code 等）配置的
    URL 通常不带尾斜杠，这里补齐精确匹配（内部 route_path 规范化为 "/"）。
    """

    def matches(self, scope):
        match, child_scope = super().matches(scope)
        if (
            match == Match.NONE
            and scope["type"] in ("http", "websocket")
            and get_route_path(scope) == self.path
        ):
            root_path = scope.get("root_path", "")
            child_scope = {
                "path": scope["path"] + "/",  # 规范化尾斜杠（root_path 剥离后为 "/"）
                "path_params": dict(scope.get("path_params", {})),
                "app_root_path": scope.get("app_root_path", root_path),
                "root_path": root_path + self.path,
                "endpoint": self.app,
            }
            return Match.FULL, child_scope
        return match, child_scope
