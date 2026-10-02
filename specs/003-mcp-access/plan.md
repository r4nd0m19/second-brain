# 实现计划（as-built）：MCP 接入

**关联**: spec.md / tasks.md / research.md；契约 contracts/mcp.md；数据模型 data-model.md

## 架构

```
Claude Code（或 dsh 等 harness）
   │  Streamable HTTP（POST/GET /mcp，Bearer 凭据）
   ▼
FastAPI（现有服务，同进程）
   ├─ ExactMount("/mcp") → MCPAuthMiddleware（scope 校验 → ContextVar{scope, owner}）
   │      → MCPServer（官方 mcp python-sdk 2.x，streamable_http_app，json_response）
   │           └─ 工具包装层 app/mcp/server.py（读 ContextVar、开 SessionLocal）
   │                └─ 纯函数实现 app/mcp/tools.py（显式 session/owner，可单测）
   │                     ├─ hybrid_search（F1 检索）
   │                     ├─ conversations/search.py（HTTP 端点共用）
   │                     └─ notes.save_note（标准入库：文件 + documents + enqueue_ingestion）
   └─ lifespan：mcp.session_manager.run()（挂载后必须由父应用驱动）
```

## 模块与文件

| 模块 | 职责 |
|------|------|
| `app/mcp/server.py` | MCPServer 实例、4 个工具包装、`ExactMount`、传输安全白名单、ASGI 组装 |
| `app/mcp/tools.py` | 工具纯函数（search_knowledge / get_document / search_conversations；ToolError 语义） |
| `app/mcp/auth.py` | ASGI 鉴权包装（Bearer → verify_scoped_token → ContextVar）、401 响应 |
| `app/notes.py` | 笔记写入服务（note 文档 + 标准入库） |
| `app/conversations/search.py` | 对话搜索核心（从 router 抽出，HTTP 与 MCP 共用） |
| `app/main.py` | 挂载 `/mcp`（ExactMount）+ lifespan 组合 |
| `web/app/page.tsx` / `lib/api.ts` | 凭据 scope 选择与展示（capture/read/write） |
| `tests/test_mcp.py` | 协议级测试（ASGI + 会话管理器后台任务 + 权限门槛 + 工具直调） |

## 关键技术点（坑与对策，详见 research.md）

1. **session_manager 生命周期**：挂载后必须由父 lifespan 驱动 `run()`；该 context 每实例仅一次且必须同任务进出（anyio cancel scope）——生产在 lifespan，测试用专用后台任务承载。
2. **ExactMount**：Starlette `Mount` 正则只认 `/mcp/...`，精确 `/mcp` 会漏给 SPA 通配路由（405/307）——子类补精确匹配。
3. **鉴权**：ASGI 包装而非 SDK 内建 verifier——401 不带 `WWW-Authenticate`（避免客户端走 OAuth 发现）；scope/owner 经 ContextVar 传入工具层。
4. **错误语义**：预期失败用 `ToolError`（消息透传模型）；其余异常只显示 "Error executing tool"。
5. **JSON 响应**：`json_response=True`（工具无流式进度；客户端解析简单）。
6. **依赖**：`mcp`（官方 python-sdk 2.x，`MCPServer`；v1 的 FastMCP 已更名）加入 pyproject。

## 测试与验证策略

- 单测：`tests/test_mcp.py`（4 个：鉴权门槛 / 握手+tools/list+真实检索 / write 门槛+写入 / get_document 回退与错误）。测试内 monkeypatch SessionLocal→测试库、假 embedding、假存储与 enqueue。
- 真实链路（2026-10-02 已执行）：curl 全链路 + `claude mcp list` Connected + save_note 写入后清理。
- 回归：server 全量单测 54 通过；web 构建通过。

## 约束回看（constitution）

- II（调研先行）：接入方式与 SDK 版本经联网调研 + 实测校准（research.md）。
- VI（解耦）：MCP 挂载/故障不影响核心问答；工具复用既有服务层，无第二套检索。
- VII（可替换/边界）：凭据 scope 为唯一权限边界；单用户 owner 过滤自第一天保留多用户路。
