# API Contracts — F1 核心问答（core-qa）

**Base**: `/api` | **认证**: HttpOnly Cookie 会话（除 login 外全部端点需登录）| **错误格式**: `{"error": {"code": "...", "message": "..."}}`

## Auth

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | `{username, password}` → 204 + Set-Cookie；失败限速（默认 5 次/15 分钟）→ 429 + `Retry-After`（T034） |
| POST | `/api/auth/logout` | 清会话，并使该账号**所有设备**上的旧会话立即失效（会话纪元 +1，R23） |
| GET | `/api/me` | → `{username}` |

## Documents（资料）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/documents` | multipart 上传 → 201 `{id, status}`；sha256 重复 → 200 `{duplicate: true, existing_id}`（FR-001）；无法解析仍 201（status=unparseable，FR-014） |
| GET | `/api/documents` | `?source=upload\|browser&q=&sort=&page=&page_size=`（缺省 upload，conversation 不列表）→ `{items,total,page,page_size}`（FR-002/009；**2026-10-02 列表增强**：`q` 匹配标题/站点/网址 + 正文子串（pg_trgm），正文命中条目附 `match{type:content,snippet}`、标题/网址命中 type=name/url；`sort`=白名单字段 + `-` 前缀倒序（upload：created_at/name/size；browser：last_captured_at/first_captured_at/visit_count/name/size，默认 -last_captured_at），非法字段 400；`page_size` 缺省 20 上限 100，`page` 越界钳制；item 负载 `{id, name, format, size, status, status_reason?, progress?, parse_hint?, created_at}`，progress=`{done,total,unit}`；**F2**：browser 附 `source_url/site_name/first_captured_at/last_captured_at/visit_count/snapshot{state,bytes}`） |
| GET | `/api/documents/{id}` | → 单文档详情（浏览页/状态查询用，FR-015） |
| GET | `/api/documents/{id}/original` | 原文件流（`Content-Disposition` 保留原名，FR-013）；`?inline=1` 返回内联视图（在线浏览用，白名单格式，FR-015） |
| POST | `/api/documents/{id}/reprocess` | 重试解析（如 embedding 故障后）；`?mode=deep` = PDF 深度解析（Docling 分批，表格/版面更完整但约 20 分钟，R7） |
| DELETE | `/api/documents/{id}` | 204；级联删除 chunks + 原文件（FR-003/011） |
| GET | `/api/documents/{id}/snapshot` | **F2**：页面快照回放（会话认证；CSP sandbox + gzip 直出；无快照 404 / 文件缺失 410） |
| DELETE | `/api/documents?source=browser&before=&after=` | **F2**：按时间范围批量清理（必须显式 source=browser）→ 200 `{deleted}`；同单条删除链路 |
| * | `/api/capture/*` | **F2**：采集接收（Bearer 凭据）/ 凭据管理（会话）——契约见 `specs/002-browser-capture/contracts/capture-api.md` |

## 统计（试用需求新增，2026-10-02）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/stats/storage` | 存储用量：`{database_bytes, storage_bytes, snapshot_bytes, snapshot_files, storage_files, documents:{upload,browser,conversation,note}}`（会话认证；资料页顶部展示；note= MCP 回存笔记，2026-10-02） |

### MCP（Claude Code 等 harness 接入，2026-10-02）

- 独立 feature：端点 / 工具 / 鉴权 / 注册示例见 **`specs/003-mcp-access/contracts/mcp.md`**（本文件不再重复）。

## Conversations（对话）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations` | → `[{id, title, created_at}]` |
| GET | `/api/conversations/search` | **2026-10-02 对话搜索**：`?q=&limit=`（q 空→空结果；limit 缺省 20 上限 50）→ `{items:[{id,title,hit_count,last_hit_at,hit:{message_id,role,snippet,created_at}}],total}`——消息正文子串匹配（user/assistant 双方；pg_trgm GIN `ix_messages_content_trgm`），会话级去重、按最近命中倒序；`hit` = 该会话最早命中消息（前端打开后滚动定位 + 短暂高亮） |
| GET | `/api/conversations/{id}/messages` | → 消息列表（含 citations/source_type） |
| DELETE | `/api/conversations/{id}` | 204（FR-011，在对话区管理） |

## Chat（核心，SSE 流式）

`POST /api/chat`  body: `{conversation_id?, message}` → `text/event-stream`：

| 事件 | 载荷 | 说明 |
|------|------|------|
| `meta` | `{conversation_id, source_type, citations?, related_hints?, time_range_label?}` | `kb`=命中（带 citations，FR-006）；`model_knowledge`=兜底（FR-007）；弱相关附 related_hints；**F2**：含时间表达的问题附 `time_range_label` 回显（浏览来源 citations 另含 `source_url`/`last_captured_at`）；**2026-10-02**：对话回写来源的 citation 另含 `conversation_id` / `message_id` / `inherited_citations`（旧引用标记的出处继承，FR-020；读取历史消息时同样富化）；**F4**：联网来源 citation `{web:true, document_id:null, source_url, quote(摘要)}`，`source_type` 新增 `web`（「来自网络」；外链新标签直开） |
| `token` | `{text}` | 增量文本（流式） |
| `done` | `{message_id, usage?, cost_cny?}` | 完成；usage 含 prompt/completion tokens，cost_cny 为估算费用（FR-017） |
| `error` | `{code, message}` | 模型故障等，可重试；历史与资料不受影响 |

**行为链**: 混合检索（pgvector + FTS）→ 高相关：基于命中片段生成 + 出处；低相关：兜底为主 + "库中可能相关"提示；无相关：兜底 → **兜底完成后异步回写库**（FR-008，messages 记 source_type=`conversation` 入库检索层）。**F2**：问题含时间表达时先解析（规则 + LLM 兜底）——`list` 意图直出浏览清单 / `search` 意图带 `last_captured_at` 过滤检索（R5 迭代扫描）；解析结果经 meta 回显。

**二次命中**: 既往对话被检索到时，回答 source_type 标注 `prior_conversation`（US3）。

## 静态与 PWA

| 路径 | 说明 |
|------|------|
| `GET /` 及前端路由 | Next.js 静态产物（FastAPI 托管，SPA 回退到 index.html） |
| `GET /manifest.webmanifest`、`/sw.js` | PWA 可安装（FR-012） |
