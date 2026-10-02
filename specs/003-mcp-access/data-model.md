# 数据模型（MCP 接入相关）

> 表结构的权威定义在 001-core-qa/data-model.md 与 002-browser-capture/data-model.md；本文件记录 MCP 引入的语义扩展。

## documents.source_type 新增 `note`

- 由 `save_note` 工具写入（`format=md`，`original_path=…/content.md`，走标准解析/入库管线 → chunks + embedding）。
- 可被检索与问答引用（orchestrator 以「笔记《名称》」标注，不标注"仅供参考"）。
- **不出现在资料列表**（同对话回写的管理边界）；当前无 UI 删除入口（可经 `DELETE /api/documents/{id}` 删除，级联清理）。
- 无 conversation 归属（`conversation_id=NULL`）；删除会话不涉及笔记。

## capture_tokens.scope 语义扩展

- 取值：`capture`（缺省；采集端点）/ `read`（MCP 只读）/ `write`（MCP 只读 + 写入回存）。
- 校验：`verify_scoped_token(session, raw, allowed_scopes)`（哈希 + 未吊销 + scope ∈ 集合）；MCP 端点允许 {read, write}；写入工具要求恰为 `write`。
- 行生命周期：吊销（`revoked_at` 置位，保留记录）→ 彻底删除（`?purge=1`，仅限已吊销）。

## 无迁移

两处均为既有 TEXT/VARCHAR 列取值扩展（`scope` 本来就设计为可扩展），**无需 Alembic 迁移**。
