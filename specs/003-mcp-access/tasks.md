# Tasks（as-built 追记）：MCP 接入

> 本 feature 为先实现后补记（用户要求直接实现）；下列任务均已完成为验收依据。
> 每项含 DoD；日期 2026-10-02。

- [x] **T001 服务端 MCP 模块**：`app/mcp/{server,tools,auth}.py` + `main.py` 挂载与 lifespan 组合
  - DoD: `/mcp` 握手（initialize/initialized/tools/list/tools/call）经真实 HTTP 全通；`ExactMount` 修无尾斜杠；session_manager 由父 lifespan 驱动 ✓
- [x] **T002 凭据 scope 扩展**：`capture/read/write`（tokens_router 校验 + `verify_scoped_token`）+ 前端选择与展示
  - DoD: capture 凭据访问 /mcp → 401；read 可用检索工具；write 才可 save_note（409 语义在工具层为 ToolError）✓
- [x] **T003 笔记写入链路**：`app/notes.py`（note 文档 + content.md + enqueue_ingestion）；`SourceType.note`；orchestrator「笔记」标注
  - DoD: save_note → documents(source_type=note, processing)→ 入库后可检索；不出现在资料列表 ✓
- [x] **T004 对话搜索抽取共用**：`app/conversations/search.py`（router 改为薄封装）
  - DoD: 既有 5 个对话搜索测试不改断言全通过；MCP `search_conversations` 复用同一核心 ✓
- [x] **T005 协议级测试**：`tests/test_mcp.py`（4 用例：鉴权门槛 / 握手+工具列表+真实检索 / 写入门槛与写入 / get_document 回退+ToolError）
  - DoD: 全量单测 54 通过（含新增 4）✓
- [x] **T006 真实链路验证**：curl 全链路（握手/工具/真实语料检索/写入并清理）；`claude mcp list → second-brain ✔ Connected`
  - DoD: 检索返回真实语料（评分/片段/页码）；测试笔记创建后经 API 删除、临时凭据吊销+删除 ✓
- [x] **T007 Claude Code 注册**：user scope 注册（凭据「Claude Code（MCP）」write）；Windows 端使用说明（局域网 URL）
  - DoD: `claude mcp list` Connected；新会话生效说明已给出 ✓
- [x] **T008 文档同步**：本目录 spec/plan/tasks/contracts/research/data-model；001/002 指针；project.md 登记
  - DoD: 001 contracts MCP 段与 research R13 改指针；002 凭据 scope 行已更新（先前完成）✓

## Notes

- 依赖：官方 `mcp` python-sdk 2.x（已加入 pyproject）；无新增数据库迁移（scope 为 TEXT 列，note 为无约束 VARCHAR 枚举）。
- 后续（未决）：笔记的 UI 列表/管理入口；read-only 凭据的注册示例文档化到 quickstart（如需）。
