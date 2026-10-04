# MCP 契约（Streamable HTTP）

> 从 001-core-qa/contracts/api.md 迁入（2026-10-02 文档审计）。

## 端点与鉴权

- `POST/GET /mcp`：同进程挂载于现有服务（`json_response` 模式）。
- 鉴权：`Authorization: Bearer <凭据>`——scope 必须为 `read` 或 `write`；`capture` 凭据拒绝（401，响应体为 JSON 错误、不带 `WWW-Authenticate`）。
- DNS-rebinding 白名单：默认 `localhost` / `127.0.0.1`（含 `:8000`）；局域网/域名 host 经 `MCP_ALLOWED_HOSTS` 配置追加（T093，2026-10-04；公开仓库不再硬编码作者内网 IP）。
- 协议：MCP Streamable HTTP（官方 python-sdk 2.x；initialize → notifications/initialized → tools/list → tools/call；会话 id 经 `mcp-session-id` 头）。

## 工具

| 工具 | 入参 | 返回（JSON） | 权限 |
|------|------|--------------|------|
| `search_knowledge` | `query`, `limit=8` | `[{document_id, name, source_type, heading, page, score, snippet, source_url?, last_captured_at?}]`（资料/网页/笔记混合检索） | read |
| `get_document` | `document_id`, `max_chars=20000` | `{document_id, name, format, source_type, source_url, created_at, truncated, content}`（无原文件时内容块拼接） | read |
| `search_conversations` | `query`, `limit=10` | 会话级命中 `[{id, title, hit_count, last_hit_at, hit:{message_id, role, snippet, created_at}}]` | read |
| `save_note` | `title`, `content`, `source="Claude Code (MCP)"` | `{id, status}`（`source_type=note`，标准入库） | **write** |

预期失败以 `ToolError` 返回（`isError=true`，消息透传模型）；其余异常仅为 "Error executing tool …"。

## CLI 注册示例

```bash
claude mcp add --transport http --scope user second-brain http://localhost:8000/mcp \
  --header "Authorization: Bearer sb_cap_…"
```

## 凭据（scope 语义）

| scope | 用途 | 可用面 |
|-------|------|--------|
| `capture` | 浏览器扩展采集写入 | `/api/capture/pages`、`/api/capture/ping` |
| `read` | MCP 只读 | /mcp 检索类工具 |
| `write` | MCP 只读 + 写入回存 | /mcp 全部工具（含 save_note） |

生成入口：资料页 → 浏览记录 → 采集凭据（选择用途）；管理：吊销（保留记录）→ 彻底删除（先吊销后删除）。数据传输对象见 002-browser-capture/contracts/capture-api.md（凭据管理表）。
