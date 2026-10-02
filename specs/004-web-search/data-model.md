# 数据模型：联网检索（库外兜底）

**本 feature 无新表、无字段、无迁移。** 说明如下：

## 实体形状（均为临时/既有容器内，不新增持久化结构）

### WebSearchResult（临时，不持久化）
| 字段 | 类型 | 说明 |
|------|------|------|
| title | str | 网页标题（智谱 `title`） |
| url | str | 网页链接（智谱 `link`） |
| snippet | str | 摘要（智谱 `content`，按 `WEB_SEARCH_SNIPPET_MAX` 截断） |
| site_name | str \| None | 站点名（`media`） |
| published_at | str \| None | 发布日期（`publish_date`） |

> 生命周期：单次回答过程内存在（内存）；不落库、不入检索、不进备份（FR-005）。

### Web 来源引用（写入既有 `messages.citations` JSONB）
```json
{
  "document_id": null, "chunk_id": null,
  "document_name": "网页标题", "heading_path": null, "page": null,
  "quote": "摘要片段", "source_url": "https://…", "web": true
}
```
- 与本地引用的区别：`web: true` + `document_id=null`；前端据此渲染外链（新标签）
- 随消息持久化（与本地 citations 同容器），随会话删除级联消亡（无新增删除面）

### messages.source_type 新增取值 `web`
- 取值域：`kb` / `model_knowledge` / `prior_conversation` / **`web`**（"来自网络"）
- 枚举为 VARCHAR(32) 无 CHECK 约束（既有先例：browser/note 同做法）→ **无迁移**

## 配置（config.py / .env，非数据库）
`WEB_SEARCH_API_KEY`（空=能力关闭）· `WEB_SEARCH_MAX_RESULTS`(5) · `WEB_SEARCH_SNIPPET_MAX`(800) · `WEB_SEARCH_TIMEOUT_S`(5.0) · `WEB_SEARCH_FRESHNESS`("noLimit") · `WEB_SEARCH_ENGINE`("search_std") · `WEB_SEARCH_FALLBACK_ENGINE`("search_pro_sogou") · `WEB_SEARCH_DAILY_LIMIT`(30，0=不限；进程内计数护栏)
