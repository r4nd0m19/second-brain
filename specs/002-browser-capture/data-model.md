# Data Model — F2 浏览器采集（browser-capture）

**约定**: 沿用 F1 约定（全表 `owner_user_id`、时间戳 UTC、删除级联）；本文件只列**新增与变更**，F1 实体见 `../001-core-qa/data-model.md`。

## documents（变更：新枚举值 + 扩展列）

`source_type` 新增枚举值 **`browser`**（非原生枚举 VARCHAR+CHECK，迁移 = 重建 CHECK）。`source_type='browser'` 的行即 spec 中的**网页条目（WebPage）**——不建新表，复用 owner / 删除 / 备份 / 检索体系。

既有字段在浏览器来源下的语义：

| 字段 | 语义 |
|------|------|
| name | 网页标题（缺省回退 URL） |
| format | `html`（固定） |
| size_bytes | **正文文本字节数**（仅元信息条目为 0） |
| sha256 | `sha256(正文文本)` —— 内容判重；正文未变 → 跳过重分块 / 重嵌入 |
| original_path | 正文文本文件相对路径（`{owner}/{doc}/content.md`；无正文时为空文件占位） |
| status / status_reason | `processing → indexed`；仅元信息条目 = `indexed` + 原因说明（不用 unparseable——提取失败 ≠ 解析失败） |

新增列（全部 NULLABLE，上传类资料不填）：

| 字段 | 类型 | 说明 |
|------|------|------|
| source_url | text | 原网页 URL（规范化：去 fragment，保留查询串） |
| site_name | text | 域名（host），列表展示用 |
| first_captured_at / last_captured_at | timestamptz | 首次 / 最近浏览（FR-011；时间检索与"看过哪些"列表用 last） |
| visit_count | int | 访问次数（FR-005） |
| snapshot_path | text NULL | `{owner}/{doc}/snapshot.html.gz`；NULL = 未保留 |
| snapshot_bytes | bigint NULL | 快照压缩后字节数（存储统计与列表展示用） |
| snapshot_state | text NULL | `kept` / `skipped_oversize` / `skipped_error`（NULL = 非浏览器来源） |
| capture_id | uuid NULL | 最近一次采集事件的幂等键（重试去重，不重复计数） |

**索引**: partial UNIQUE `(owner_user_id, source_url) WHERE source_type='browser'`（同 URL 一条目，FR-005）；B-tree `(source_type, last_captured_at)`（时间过滤，R5）；既有 `(owner, sha256)` 保留。

**状态机（browser 行）**:
- 新采集 → `processing`（后台：正文分块 + embedding）→ `indexed`。
- 重访（同 URL）：`last_captured_at` / `visit_count` 更新；正文 hash 变化 → 删旧 chunks → 重新分块嵌入（回到 processing → indexed）；未变 → 仅更新元数据与快照。`capture_id` 与上次相同 → **幂等 no-op**（不计数）。
- 仅元信息（正文提取失败或扩展配置关闭）→ `indexed`（0 chunks）。

**迁移**: documents 新增列 + source_type CHECK 重建 + 两个索引，单个 Alembic 迁移完成。

## capture_tokens（新表；spec 实体 CaptureToken）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | uuid PK | |
| owner_user_id | uuid FK users | 归属（VII） |
| name | text | 设备 / 用途标识（如 "Windows Chrome"） |
| prefix | text | 明文前缀（`sb_cap_` 后 8 字符），列表识别用 |
| token_hash | text | `sha256(token)`；**明文仅创建响应返回一次**（show once） |
| scope | text | 默认 `capture`（权限边界 = 仅采集端点；为 B1 等未来采集器复用同机制留路） |
| created_at / last_used_at / revoked_at | timestamptz | `last_used_at` 节流更新；吊销 = `revoked_at` 置值（保留审计行） |

**校验**: hash 匹配 + `revoked_at IS NULL` + scope 覆盖端点族 → 401（无效 / 吊销）与 403（scope 不符）区分。

## chunks（复用，无结构变更）

- 浏览器来源分块：轻量 Markdown 分块器（标题层级 + 长度上限），`heading_path` = 标题路径，`page = NULL`。
- 时间过滤检索在 `chunks ⋈ documents` 上进行（R5 查询形态），chunks 表不加列。

## 客户端本地实体（扩展，不落服务器）

| 实体 | 存储 | 说明与理由 |
|------|------|------------|
| BlockRule（黑名单 + 全局暂停） | `chrome.storage.local` | 源头不采最彻底实现：**连黑名单元数据都不落服务器**（FR-004）；离线可用 |
| CaptureQueue（待传 / 重试队列） | IndexedDB（payload 大对象）+ `storage.local`（状态） | 先落盘再发送（R2）；非服务器实体（spec 已注明） |
| 连接设置（URL + token） | `storage.local` + `setAccessLevel('TRUSTED_CONTEXTS')` | content script 不可读（R2） |
| URL 规范化规则 | 代码（与服务端一致） | 去 fragment、保留查询串 |

## 删除 / 清理 / 备份链路（constitution V）

1. **单条删除**：既有 `DELETE /api/documents/{id}` → BlobStore 目录级联（含 content.md + snapshot.html.gz）+ chunks CASCADE。
2. **时间范围清理**：`DELETE /api/documents?source=browser&before&after` → 同链路批量。
3. **备份**：`storage-mirror`（`rsync --delete`）自动包含快照、自动同步删除（已核对 backup.sh）；DB dump 覆盖新表新列。
4. **导出**：正文经既有 `original` 端点下载（content.md）；快照经 snapshot 端点（inline 或另存）。

## 多用户留路自检

- [x] documents / capture_tokens 均带 `owner_user_id`，查询过滤
- [x] 快照存储按归属分区（既有 BlobStore 模式）
- [x] token per-owner 生成 / 吊销；scope 列可扩展新采集器
- [x] 检索 / 分块 / 存储接口无单用户假设

## 已知局限（记录的近似语义）

- 时间检索以 `last_captured_at` 为"看过"依据（仅记首次 / 最近 + 次数，不做访问事件表——Non-Goal：浏览行为分析）。同一 URL 跨多个时间窗访问时只归属最近一次："我上周看过哪些"对"上周访问过、此后又访问"的条目会漏（可接受，记录在案）。
- 同 URL 历史版本不保留（spec 已定：覆盖更新为最新；v1 不保留历史版本）。
