# Data Model — F1 核心问答（core-qa）

**约定**: 所有表携带 `owner_user_id`（v1 单用户取固定值；查询自第一天按归属过滤 —— constitution VII）；时间戳 UTC；删除级联（FR-011）。

## users

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| username | text UNIQUE | |
| password_hash | text | argon2/bcrypt |
| created_at | timestamptz | |

单用户阶段 = 白名单单账号（认证边界第一天存在，为多用户留路）。

## documents（资料）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| owner_user_id | uuid FK users | 归属 |
| name | text | 原文件名 |
| format | text | pdf / epub / txt / md / docx / 其他 |
| size_bytes | bigint | |
| sha256 | text | 内容判重（同 owner 相同 → 拒绝并提示，FR-001） |
| status | enum | `processing` / `indexed` / `unparseable`（FR-002/014） |
| status_reason | text NULL | 无法解析原因（扫描版/格式不支持/损坏）；解析中为进度文案 |
| parse_hint | text NULL | 解析质量提示（表格较多→建议深度解析；R7） |
| source_type | enum | `upload` / `conversation`（FR-008 回写；对话来源不进资料列表，FR-009）/ `browser`（F2）/ `note`（MCP 写入回存，2026-10-02；不进资料列表，同对话回写管理边界） |
| conversation_id | uuid FK NULL | 回写会话 ↔ 文档链接（FR-008；仅 conversation 来源有值） |
| original_path | text | 原文件存储位置（字节级保真，FR-013） |
| created_at / updated_at | timestamptz | |

**状态机**: `processing → indexed`（解析+分块+embedding 全部完成）／`processing → unparseable`（判定后保留原文件与登记，FR-014）；embedding 服务故障 → 停留 `processing` + 原因，可重试。

## chunks（内容块）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| document_id | uuid FK documents CASCADE | |
| owner_user_id | uuid | 冗余，检索过滤用 |
| content | text | 块文本 |
| heading_path | text | 标题路径（Docling HybridChunker 产出，如 "3.2 检索增强"） |
| page | int NULL | PDF 页码 |
| chapter / paragraph | text / int NULL | 章节 / 段落序号 |
| embedding | vector(1024) | 维度按 provider（bge-m3=1024）；换 provider 需重建（配置化） |
| created_at | timestamptz | |

**索引**: HNSW（embedding, cosine）；pg_trgm GIN（content，中文关键词检索，T033/R9）。

## conversations（对话）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| owner_user_id | uuid | |
| title | text | 默认取首问前 20 字（可配置） |
| created_at | timestamptz | |

## messages（消息）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| conversation_id | uuid FK CASCADE | |
| owner_user_id | uuid | |
| role | enum | `user` / `assistant` |
| content | text | |
| source_type | enum NULL | assistant 专属：`kb` / `model_knowledge` / `prior_conversation`（FR-005/007/008） |
| citations | jsonb NULL | `[{document_id, chunk_id, heading_path, page, quote}]`（FR-006 出处三要素；quote 长度约 ≤300 字，可配置） |
| related_hints | jsonb NULL | 弱相关提示列表（FR-007） |
| usage | jsonb NULL | 模型 token 用量 + 估算费用（FR-017；含 cost_cny） |
| created_at | timestamptz | |

**索引**: pg_trgm GIN（content，对话全文搜索，2026-10-02；`ix_messages_content_trgm`，迁移 `d51a9c73e2b4`，与 R9 同机制）。

## 多用户留路自检

- [x] 全表 `owner_user_id`，查询强制过滤
- [x] 原文件按归属分区存储（`storage/{owner}/{doc}`）；sha256 判重为 per-owner
- [x] 检索/嵌入/存储均为可替换接口，无"唯一用户"假设
