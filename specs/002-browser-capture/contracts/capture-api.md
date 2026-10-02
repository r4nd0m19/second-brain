# API Contracts — F2 浏览器采集（增量）

> F1 契约见 `../001-core-qa/contracts/api.md`；本文件列**新增端点**与**既有端点的变更**。
> 认证列：`token` = `Authorization: Bearer sb_cap_…`（capture_tokens，scope=capture）；`会话` = 既有 HttpOnly Cookie。
> 错误格式沿用 `{"error": {"code", "message"}}`。

## 采集接收（扩展 → 服务器；token 认证）

### POST /api/capture/pages

multipart/form-data，字段与 SingleFile 官方扩展「upload to REST Form API」对齐（便于手工实测 / 降级采集路径）：

| 字段 | 类型 | 说明 |
|------|------|------|
| url | text 必填 | http(s)；服务端规范化（去 fragment） |
| file | file 二选一 | 页面快照（`.html` 或 `.html.gz`） |
| text | text 二选一 | 正文 Markdown / 文本（自研扩展填；缺省 = 仅快照 + 元信息） |
| title | text 可选 | 缺省回退 url |
| captured_at | text 可选 | ISO8601；缺省 = 服务器时刻 |
| capture_id | text 可选 | UUID 幂等键（自研扩展填；缺省按 URL 更新语义处理） |

响应：

| 状态 | 载荷 | 场景 |
|------|------|------|
| 201 | `{id, duplicate:false, snapshot:"kept"\|"skipped_oversize"}` | 新条目 |
| 200 | `{id, duplicate:true}` | `capture_id` 已处理过（幂等重放，不重复计数） |
| 200 | `{id, updated:true, reindexed:bool, snapshot:"…"}` | 同 URL 更新（标题 / 正文 / 快照 / 计数） |
| 400 | 错误格式 | url 非法（**唯一 400 来源**） |
| 401 / 403 | 错误格式 | token 无效 / 已吊销 · scope 不符 |
| 413 | 错误格式 | 超出请求体天花板（100MB，防滥用） |
| 429 | 错误格式 + `Retry-After` | 按 token 限速（可配置） |

行为：快照超 `capture_max_snapshot_mb`（默认 20）→ 降级 `skipped_oversize`（不报错入库）；正文 hash 变化 → 异步重分块 + 嵌入（入库响应秒级）；快照落盘 `{owner}/{doc}/snapshot.html.gz`（先写文件、后提交 DB 行）。**缺 file 且无 text → 仅元信息条目**（spec Edge Case；更新场景不覆盖既有正文——注：Starlette 丢弃空字符串表单字段，空串与缺省等价，2026-10-02 实核）。

### GET /api/capture/ping（token 认证）

→ `200 {ok:true, owner, scope:"capture", server_version}`；`401` token 错 / `403` scope 不符（扩展「保存并测试」区分展示）。

## 快照回放（会话认证）

### GET /api/documents/{id}/snapshot

| 状态 | 说明 |
|------|------|
| 200 | 快照流：`Content-Type: text/html; charset=utf-8`；`Content-Encoding: gzip`（原样直出） |
| 404 | 条目无快照（`snapshot_state != kept`） |
| 410 | 快照文件缺失（磁盘异常，列表可标注） |

200 响应头（安全基线，R4）：

```
Content-Security-Policy: sandbox; default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'
X-Content-Type-Options: nosniff
```

前端以 `<iframe sandbox="">` 嵌入（空值 = 最大限制）。

## 资料端点变更（会话认证）

### GET /api/documents（变更：source 参数）

`?source=upload|browser`（缺省 `upload`，**F1 行为不变**）。`browser` 条目负载追加：

```json
{"source_url": "...", "site_name": "...", "first_captured_at": "...", "last_captured_at": "...",
 "visit_count": 3, "snapshot": {"state": "kept", "bytes": 1234567}}
```

### DELETE /api/documents（新增：批量清理形态）

`?source=browser&before=<ISO>&after=<ISO>`（**必须显式 source=browser** 防误删；至少一个时间界；作用于 `last_captured_at`）→ `200 {deleted: n}`（计数需要响应体；204 不允许 body——单条删除保持既有 204 无体）。

删除链路 = 单条删除同链路（BlobStore 目录级联 + chunks CASCADE；FR-007 检索 / 出处同步生效）。既有路径形态 `DELETE /api/documents/{id}` 不变。

## 采集凭据管理（会话认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/capture/tokens | → `[{id, name, prefix, scope, created_at, last_used_at, revoked_at}]` |
| POST | /api/capture/tokens | `{name}` → `201 {id, token}`——**token 明文仅此一次返回**（show once） |
| DELETE | /api/capture/tokens/{id} | 吊销（置 `revoked_at`，保留审计行）→ `204` |

## Chat / 检索（行为变更，SSE 事件结构不变）

- `meta` 事件 `citations[]`：browser 来源追加 `source_url`、`last_captured_at`（F1 字段不变）→ 前端渲染"网页"出处（标题 / 站点 / 浏览时间 + 打开原文 + 查看快照）。
- 时间意图（orchestrator 前置，内部实现）：
  - 解析 `{start, end, intent}`（规则 + LLM 兜底，R6；解析结果**回显**于回答，如"统计 9-21 ~ 9-27"）
  - `intent=list`（"我上周看过哪些网页"）→ 不经向量检索，直接清单（标题 + 站点 + 时间，按 `last_captured_at` 排序）
  - `intent=search`（"上周看过的文章里关于 X 的部分"）→ 混合检索带 `last_captured_at ∈ [start, end)` 过滤（R5；向量分支 `SET LOCAL hnsw.iterative_scan=relaxed_order`、`ef_search=100`）
  - 无时间表达 → 既有行为完全不变
