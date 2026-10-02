# 研究记录：MCP 接入（2026-10-02，用户要求）

> 原 001-core-qa/research.md R13 迁入（2026-10-02 文档审计）。

## 决策：Streamable HTTP MCP 挂载于现有服务

- **Decision**: 以 **Streamable HTTP MCP 挂载于现有服务**（`/mcp`，同端口同进程）而非 stdio 本地进程——一次实现同时服务本机与 Windows 端的 Claude Code、以及后续 dsh 等 harness；工具集 = 检索 + 读原文 + 对话搜索 + 写入回存（写入需单独 grant 的 `write` 凭据）。
- **依据**（联网调研）: Claude Code 原生支持 HTTP/stdio 两种 MCP（HTTP 带 `--header` Bearer）；社区个人知识库接入普遍以 MCP 检索工具的形态出现（knowlp-rag、dsh 生态插件）；Streamable HTTP 是当前唯一受支持的远程传输（SSE 已 EOL）。

## 实现要点（官方 mcp python-sdk 2.x，`MCPServer`）

1. 挂载后必须在父 lifespan 驱动 `session_manager.run()`——**每实例仅一次、必须同任务进出**（anyio cancel scope 约束）；测试中用专用后台任务承载。
2. Starlette `Mount` 的正则只认 `/mcp/...`，精确 `/mcp` 会漏给 SPA 通配路由（405，无通配时为 307）→ 自写 `ExactMount` 补齐精确路径。
3. `json_response=True`：工具无流式进度，JSON 响应更利于调试与客户端解析。
4. DNS-rebinding 白名单含局域网 IP（Windows 端访问）；凭据鉴权仍是硬门槛。
5. 鉴权 = CaptureToken `scope` 扩展（capture/read/write）+ 自写 ASGI 包装：401 **不带 `WWW-Authenticate`**（避免客户端触发 OAuth 发现流程）；scope/owner 经 ContextVar 传工具层；write 工具在工具层二次把关。
6. 工具预期错误用 `ToolError`（`isError=true`，消息透传模型）；其它异常仅显示 "Error executing tool …"。
7. 工具实现为纯函数（显式 session/owner）→ 可单测；对话搜索核心抽到 `app/conversations/search.py` 供 HTTP 端点与 MCP 共用；笔记写入复用标准入库管线（`SourceType.note`）。

## 验证

- 真实服务 curl 全链路：握手 → tools/list → 检索真实语料（返回评分/片段/页码）→ save_note 写入 `source_type=note` 并清理。
- `claude mcp list` → `second-brain ✔ Connected`。
- 协议级测试 4 例 + 全量单测 54 通过。
