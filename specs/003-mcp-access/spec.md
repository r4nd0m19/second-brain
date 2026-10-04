# Feature Specification：MCP 接入（Claude Code 等 harness）

**Feature Branch**: 随 002-browser-capture 分支落地（2026-10-02；未单独开分支）
**Created**: 2026-10-02
**Status**: Implemented（as-built 追记：先按用户要求实现，事后补规格）

## 背景与问题

第二大脑的检索/问答目前只在自家 PWA 里可用；用户日常在 Claude Code 等 agent harness 里工作时，无法让 agent 使用其个人知识库（资料 / 浏览记录 / 对话 / 笔记）。目标：以 **MCP（Model Context Protocol）** 把第二大脑暴露为 harness 可调用的工具集，并支持把结论回存进库。

## 用户场景

### US1（P1）在 harness 中检索个人知识

**场景 1**：Given Claude Code 已配置第二大脑 MCP、服务运行中；When 用户问"我存过的资料里 SDD 是怎么定义的"；Then agent 调用 `search_knowledge` 得到命中片段/出处/网页链接，基于结果作答。
**场景 2**：Given 检索命中了一个 document_id；When agent 需要全文核对；Then 调用 `get_document` 取正文（长文截断）。
**场景 3**：Given 用户想找以前聊过的话题；When agent 调用 `search_conversations`；Then 返回会话级命中（标题/片段/命中数）。

### US2（P2）回存笔记

**场景 4**：Given 使用 write 凭据；When agent 调用 `save_note` 存下结论；Then 生成 `source_type=note` 的文档、走标准入库、此后可被检索/问答引用（对话中以「笔记」标注）。
**场景 5**：Given 使用 read 凭据；When agent 调用 `save_note`；Then 工具返回明确错误（"需要写入权限"）透传给模型，不产生任何写入。

### 验收映射

- 协议级测试：`server/tests/test_mcp.py`（握手/权限门槛/工具调用/写入清理）；全量单测 54+ 通过。
- 真机链路（2026-10-02）：curl 全链路握手 → tools/list → 真实语料检索 → save_note 写入并清理；`claude mcp list` → `second-brain ✔ Connected`。
- 注册：`claude mcp add --transport http --scope user second-brain http://localhost:8000/mcp --header "Authorization: Bearer …"`。

## Requirements *(mandatory)*

- **FR-001**: 提供 MCP 服务端（Streamable HTTP），**挂载于现有服务的 `/mcp`**（同进程同端口），供 Claude Code 等 harness 接入；不引入独立进程/端口。
- **FR-002**: 鉴权沿用凭据体系并**扩展 scope**：`read`（检索类工具）/ `write`（含写入回存；写入需显式生成 write 凭据 = 单独 grant）；`capture` 凭据不可用于 MCP；凭据可吊销、可彻底删除（先吊销后删除）。
- **FR-003**: 工具集（本版）：`search_knowledge(query, limit)`（资料/网页/笔记混合检索，返回片段+出处+网页链接）、`get_document(document_id, max_chars)`（全文；无原文件时内容块拼接）、`search_conversations(query, limit)`（对话消息正文搜索，会话级聚合）、`save_note(title, content, source)`（**仅 write**）。
- **FR-004**: 写入回存 = `source_type=note` 的资料文档，**走标准解析/入库管线**（chunk + embedding，可被检索与问答引用）；不出现在资料列表（管理边界同对话回写）。
- **FR-005**: 安全边界：DNS-rebinding 防护白名单仅放行本机与已知局域网地址；未带有效凭据一律 401（响应不带 `WWW-Authenticate`，避免客户端触发 OAuth 发现）。

## Edge Cases

- **无凭据 / capture 凭据**访问 `/mcp` → 401（明确 JSON 错误体）。
- **read 凭据调用 save_note** → 工具级错误（`ToolError`，消息透传模型可自我纠正）。
- **服务未启动**：harness 侧连接失败并提示——不影响第二大脑自身（解耦，constitution VI）。
- **Windows 端经局域网访问**：`http://<服务器局域网IP>:8000/mcp` —— 需在 `server/.env` 的 `MCP_ALLOWED_HOSTS` 显式列出该 host（含端口；默认白名单仅本机，T093 起不再硬编码）；凭据同。
- **无尾斜杠 `/mcp`**：必须直接命中（Starlette Mount 默认只认 `/mcp/`，已用 `ExactMount` 修正，否则落到 SPA 通配 405）。
- **笔记管理**：当前不进资料列表、无 UI 删除入口（可经 API 删除）；后续增强时再放开。

## Key Entities

- **CaptureToken**：`scope` 扩展为 `capture` / `read` / `write`（表定义见 001/002 数据模型，本目录 data-model.md 记 MCP 语义）。
- **Document**：`source_type` 新增 `note`（MCP 回存笔记）。

## Non-Goals（本版不做）

- 不做 OAuth 流程（静态 Bearer 凭据即可）；不做 MCP resources/prompts（仅 tools）；不做多用户；不做笔记的 UI 列表/管理页；不做 stdio 传输（HTTP 一份实现同时服务本机/Windows/未来的 dsh 等 harness）。

## Assumptions

- 单用户自用：MCP 工具以凭据所属 owner 过滤数据（沿用全表 owner 边界）。
- 工具返回结构化 JSON（文本块）；检索复用 F1 混合检索与 R9 索引；对话搜索复用 d51a9c73e2b4 索引。
