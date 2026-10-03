# second-brain 项目规则（Claude Code）

> 全局规则见 `~/.claude/CLAUDE.md`；本文件为项目级补充，每次会话自动加载。

## 文档同步（NON-NEGOTIABLE）

任何改动收尾时，必须对照下表同步文档；**未同步 = 未完成**。

| 改动类型 | 同步到 |
|----------|--------|
| 行为 / 需求变化（功能、交互、边界、流程顺序） | `specs/*/spec.md` + `specs/*/tasks.md`（描述/DoD/勾选） |
| 接口变化（端点、载荷、参数） | `specs/*/contracts/api.md` |
| 数据模型变化（表、字段、迁移） | `specs/*/data-model.md` |
| 技术决策 / 选型 / 调研结论（constitution II） | `specs/*/research.md`（决策 + 理由 + 备选及放弃原因） |
| 架构 / 结构 / 模块变化 | `specs/*/plan.md` |
| 项目级决策（跨 feature：愿景、范围、路线） | `.specify/memory/project.md` |

**收尾报告要求**：每次任务收尾必须列出「本次同步的文档」清单；确无同步需要时，明确写「无需同步」+ 理由（不允许默默跳过）。

**机械兜底**：`.githooks/pre-commit` 在"有代码改动但零文档改动"时打印提醒（不阻断，`--no-verify` 可跳过）。里程碑 / 批量提交后建议跑一次 `/speckit-analyze` 兜底审计（已含 G. 范式偏离检查——新增特判/清单类常量对照业界复核）。

## 运行备忘

- 本机服务：手动拉起（`cd server && .venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0`）；**不做持久化**（2026-10-01 决定，测试期；上线时随 T035 配 systemd）
- 备份：`deploy/backup/`（本地加密备份 + 恢复脚本 + 演练；异地对象存储同步延后至部署阶段，见 research R8）
- 索引维护：删除量大或出现"库里有的检索不到"时，`REINDEX INDEX ix_chunks_embedding_hnsw` + `VACUUM chunks`（HNSW 删改 churn 召回退化，见 001 research R16；检索已配 `retrieval_ef_search=200` 兜底）
- 联网检索：默认 **DeepSeek 服务端搜索**（T086：`WEB_SEARCH_PROVIDER=deepseek`——官方 Anthropic 兼容端点 + web_search 服务端工具，复用 llm key、token 计费（联网轮 ≈2–5 分）、质量=官方索引级，见 R40）；**自建 SearXNG** 保留为免费可切换源（deploy compose 内 searxng 服务——`docker compose -f deploy/docker-compose.yml up -d searxng`；127.0.0.1:8888，JSON 接口；引擎集见 `deploy/searxng/settings.yml`：实机裁剪为 sogou + bing@cn.bing.com + 360search；R39/T085）；付费源（智谱）默认关闭（`web_search_paid_fallback`）
