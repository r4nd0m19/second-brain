# Tasks: F1 核心问答（core-qa）

<!--
  结构约束：阶段结构、每任务的 Deps/DoD 子项不得删减；变更须经用户确认。
  依据：.specify/memory/constitution.md「文档结构合规」原则。
-->

**Input**: 设计文档来自 `/specs/001-core-qa/`

**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/api.md ✅ · quickstart.md ✅

**Tests**: v1 不做 TDD；测试任务仅含基础脚手架（T013）与验收脚本（T032，对应 quickstart 场景 1-9）

**Organization**: 任务按 user story 分阶段，保证每个 story 可独立实现与验证

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story（US1~US4）；Setup / Foundational / Polish 阶段无此标签
- 每个任务必须跟随两行缩进子项：
  - `Deps:` 依赖的任务 ID；无依赖写 `Deps: 无`
  - `DoD:` 该任务的完成标准，必须可验证

## Path Conventions

源码根目录：`server/`（Python 后端）· `web/`（Next.js 前端）· `deploy/`（部署与备份）

---

## Phase 1: Setup（项目初始化）

**Purpose**: 建立项目骨架与开发环境

- [ ] T001 创建项目骨架：`server/`（pyproject.toml + app/ 包）、`web/`、`deploy/`、`.env.example`
  - Deps: 无
  - DoD: 目录结构与 plan.md「Project Structure」一致；`pip install -e server`、`npm install --prefix web` 可执行
- [ ] T002 [P] Postgres 16 + pgvector 容器：`deploy/docker-compose.yml`（db 服务）
  - Deps: T001
  - DoD: `docker compose up -d db` 后 `CREATE EXTENSION vector` 成功
- [ ] T003 [P] FastAPI 骨架：`server/app/main.py`（`/health` + pydantic-settings 配置加载）
  - Deps: T001
  - DoD: `uvicorn` 启动成功，`GET /health` 返回 200
- [ ] T004 [P] Next.js 骨架：`web/`（App Router、`output: 'export'`、基础布局）
  - Deps: T001
  - DoD: `npm run build` 产出 `web/out` 静态文件
- [ ] T005 [P] 代码质量工具：ruff（server）+ eslint/prettier（web）
  - Deps: T001
  - DoD: lint 命令可执行且通过空项目检查

**Checkpoint**: 前后端骨架可构建、数据库可启动

---

## Phase 2: Foundational（阻塞性基础）

**Purpose**: 所有 user story 的共同前提

**⚠️ CRITICAL**: 本阶段完成前，任何 user story 不可开始

- [ ] T006 数据模型：`server/app/models/`（users / documents / chunks / conversations / messages，**全表带 owner_user_id**）
  - Deps: T003
  - DoD: 字段与 data-model.md 逐项一致（含 status/source_type 枚举、citations jsonb、sha256 判重字段）
- [ ] T007 数据库迁移：`server/alembic/`（建表 + pgvector 扩展 + HNSW 索引 + FTS 索引）
  - Deps: T002, T006
  - DoD: `alembic upgrade head` 建出全部表与索引；`downgrade base` 可回滚
- [ ] T008 认证边界：`server/app/auth/`（单用户白名单单账号，argon2 + HttpOnly 会话 Cookie + 全 API 守卫）
  - Deps: T003, T007
  - DoD: 未登录访问任一 `/api` 端点返回 401；登录后放行；账号来自 `.env` 初始化（constitution VII）
- [ ] T009 [P] 原文件存储抽象：`server/app/storage/`（本地磁盘实现，`storage/{owner}/{doc}` 分区 + sha256 工具）
  - Deps: T003
  - DoD: 存/取/删与 sha256 校验测试通过；接口为抽象基类（可替换）
- [ ] T010 [P] Embedding provider：`server/app/ingestion/embedding.py`（默认硅基流动 bge-m3，`.env` 可切百炼）
  - Deps: T003
  - DoD: 文本 → 1024 维向量；provider 通过配置切换，接口可替换
- [ ] T011 [P] 对话模型客户端：`server/app/chat/llm.py`（DeepSeek 默认、`.env` 可切；流式接口）
  - Deps: T003
  - DoD: 逐 token 流式输出可用；异常可捕获（供降级路径使用）
- [ ] T012 静态托管：`server/app/main.py`（挂载 `web/out` + SPA 回退，`/api` 优先）
  - Deps: T004
  - DoD: 浏览器访问 `:8000` 打开前端；未知路径回退 `index.html`
- [ ] T013 测试脚手架：`server/tests/`（pytest + 独立测试数据库 fixture）
  - Deps: T007
  - DoD: `pytest` 可运行（含测试库自动建/清）

**Checkpoint**: 骨架就绪，user story 实现可以开始

---

## Phase 3: User Story 1 - 上传资料并基于内容问答 (P1) 🎯 MVP

**Goal**: 上传文档 → 解析入库 → 提问得到**带出处**的回答

**Independent Test**: 上传一份含明确内容的文档 → 提一个只有该文档能回答的问题 → 回答正确且出处指向该文档

- [ ] T014 [US1] 上传端点：`server/app/documents/router.py`（multipart、sha256 判重 FR-001、登记 processing、存原文件）
  - Deps: T008, T009
  - DoD: 201 `{id,status}`；相同内容返回 200 duplicate（契约符合 contracts/api.md）
- [ ] T015 [US1] Docling 解析管线：`server/app/ingestion/parser.py`（PDF/EPUB/TXT/MD/DOCX；扫描件/损坏 → unparseable + 原因，FR-014）
  - Deps: T013, T014
  - DoD: 文本型 PDF 解析出带标题路径的文档树；扫描版 PDF 判定 unparseable 且保留登记
- [ ] T016 [US1] 分块 + embedding 入库：`server/app/ingestion/pipeline.py`（HybridChunker → heading_path/page/chapter 入 chunks）
  - Deps: T010, T015
  - DoD: 样例书产出 chunks（含 heading_path 与 page）；status→indexed；SC-001 计时（300 页内 <5 分钟）
- [ ] T017 [US1] 后台任务执行器：`server/app/ingestion/tasks.py`（进程内异步 + reprocess 端点）
  - Deps: T016
  - DoD: 上传立即返回、解析后异步完成；`POST /api/documents/{id}/reprocess` 可重试
- [ ] T018 [US1] 资料管理端点：`server/app/documents/router.py`（列表 / 原文件下载 FR-013 / 删除级联 FR-003+011）
  - Deps: T008, T009
  - DoD: 下载文件 sha256 与上传件一致（SC-006）；删除后 chunks 与原文件同步消失
- [ ] T019 [US1] 混合检索：`server/app/retrieval/search.py`（pgvector + FTS + 相关度分数；可替换接口）
  - Deps: T007, T016
  - DoD: 语义相近的提问命中正确 chunk；返回含 document/chunk 元数据与分数
- [ ] T020 [US1] 对话端点（命中分支）：`server/app/chat/router.py`（编排 + SSE：meta/token/done/error）
  - Deps: T011, T019
  - DoD: 命中时 `meta.citations` 含 资料名+位置+引用片段（FR-006）；事件序列符合 api.md
- [ ] T021 [US1] 前端-资料页：`web/app/`（登录页 + 上传进度/状态/列表/下载/删除）
  - Deps: T012, T018
  - DoD: 浏览器完成 上传 → 看到 indexed → 下载 全流程
- [ ] T022 [US1] 前端-对话页：`web/app/chat/`（SSE 渲染 + 出处展示：资料名/位置/可展开引用片段）
  - Deps: T012, T020
  - DoD: 提问书中细节 → 流式回答 + 出处可见（quickstart 场景 2 手工通过）

**Checkpoint**: US1 独立可用 —— **MVP 达成**，可开始真实使用与验收

---

## Phase 4: User Story 2 - 库外问题由外部模型兜底 (P2)

**Goal**: 库中无相关内容时兜底回答，并明确标注来源类型

**Independent Test**: 空库/库外问题提问 → 得到回答且标注"来自模型知识"

- [ ] T023 [US2] 检索判定与兜底分支：`server/app/chat/orchestrator.py`（阈值判定 → model_knowledge + related_hints，FR-007）
  - Deps: T020
  - DoD: 库外问题走兜底并标注来源；弱相关附"库中可能相关"提示且不混入主回答
- [ ] T024 [US2] 模型故障降级：`server/app/chat/`（error 事件 + 可重试，不影响历史与资料）
  - Deps: T023
  - DoD: 断开模型 API 后提问得到明确错误；恢复后重试成功
- [ ] T025 [US2] 前端：来源类型标注 + "库中可能相关"提示 UI：`web/app/chat/`
  - Deps: T023
  - DoD: "模型知识"标注清晰可辨；弱相关提示可展开查看

**Checkpoint**: US1 + US2 均独立可用

---

## Phase 5: User Story 3 - 兜底问答回写闭环 (P3)

**Goal**: 兜底问答入库；二次提问命中"既往对话"

**Independent Test**: 问库外问题 → 再问同一问题 → 第二次来自库且无新模型调用

- [ ] T026 [US3] 回写管线：`server/app/chat/writeback.py`（问答对 → source_type=conversation，分块 + embedding，FR-008）
  - Deps: T010, T023
  - DoD: 兜底完成后问答入库且可被检索；回写失败不阻塞用户回答
- [ ] T027 [US3] 二次命中标注 + 对话历史端点：`server/app/conversations/router.py`（prior_conversation；列表/消息/删除 FR-009+011）
  - Deps: T026
  - DoD: 重复提问命中既往对话且无新模型调用（SC-004）；删除对话生效
- [ ] T028 [US3] 前端-对话历史：`web/app/`（侧栏：列表/查看/删除）
  - Deps: T027
  - DoD: UI 中可查看与删除历史会话（对话区，不出现在资料列表 —— FR-009）

**Checkpoint**: 数据自增长闭环成立

---

## Phase 6: User Story 4 - 可安装 Web 应用（双端） (P4)

**Goal**: Windows/Android 双端"安装"为应用形态

**Independent Test**: Windows 安装与 Android 添加到主屏，各完成一次问答

- [ ] T029 [US4] PWA 支持：`web/public/`（manifest + Service Worker + 图标）
  - Deps: T012
  - DoD: Windows"安装"为独立窗口；Android 添加主屏后以应用形态（无地址栏）可用（SC-005）
- [ ] T030 [US4] 移动端适配：`web/app/`（对话/资料页响应式）
  - Deps: T029
  - DoD: 手机上完成 上传/提问/看出处 全流程可用

**Checkpoint**: 四端故事全部独立可用

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 备份、验收、安全与部署

- [ ] T031 备份机制：`deploy/backup/`（本地每日 pg_dump + 原文件增量 → 异地对象存储同步 + 恢复脚本）
  - Deps: T007, T009
  - DoD: 定时产出备份且异地有副本；恢复演练 1 次通过（SC-008）
- [ ] T032 [P] 验收脚本：`server/tests/acceptance/`（quickstart 场景 1-9 自动化）
  - Deps: T022, T027, T029, T031
  - DoD: `pytest tests/acceptance/` 全绿（覆盖 SC-001~008）
- [ ] T033 [P] 中文 FTS 落地与检索调优：`server/alembic/` + `server/app/retrieval/`（zhparser 或 pg_trgm）
  - Deps: T019
  - DoD: 中文关键词检索可用；混合检索权重可配置
- [ ] T034 [P] 安全加固：`deploy/` + `server/app/auth/`（登录限速、HTTPS/Caddy 部署说明、密钥清单）
  - Deps: T008
  - DoD: 登录限速生效；部署文档含 HTTPS 完整步骤
- [ ] T035 部署上线：`deploy/`（生产 compose + 服务器初始化文档，2C4G + Caddy + 自启）
  - Deps: T031
  - DoD: 一台全新服务器按文档 30 分钟内跑起可访问的 PWA（对照 quickstart 逐项）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2)**: 依赖 Setup —— **阻塞所有 user story**
- **User Stories (Phase 3+)**: 均依赖 Foundational；US1（MVP）必须最先；US2/US3/US4 在 US1 后可并行推进（见各任务 Deps）
- **Polish (Phase 7)**: 依赖对应 story 完成（T031 仅依赖 Phase 2；T032 依赖全部 story）

### User Story Dependencies

- **US1 (P1)**: Foundational 后可开始 —— 无 story 间依赖
- **US2 (P2)**: 依赖 US1 的对话端点（T020），依赖关系已标注
- **US3 (P3)**: 依赖 US2 的兜底分支（T023）
- **US4 (P4)**: 仅依赖基础托管（T012），与 US2/US3 并行

### Within Each User Story

- 模型/管线 → 端点 → 前端；后端先行，前端依赖契约
- 每个 story 完成其 Checkpoint 后即可独立验证

### Parallel Opportunities

- T002-T005（Setup 内 4 项互不依赖）
- T009-T011（存储/embedding/LLM 三个抽象层）
- T032-T034（Polish 内 3 项）
- US4（T029-T030）可与 US2/US3 并行（不同文件）

## Parallel Example: User Story 1

```text
# Foundational 并行层：
Task: "T009 原文件存储抽象 server/app/storage/"
Task: "T010 Embedding provider server/app/ingestion/embedding.py"
Task: "T011 对话模型客户端 server/app/chat/llm.py"

# US1 内后端就绪后，前后端可部分并行：
Task: "T021 前端-资料页 web/app/"
Task: "T022 前端-对话页 web/app/chat/"
```

## Implementation Strategy

### MVP First（US1 only）

1. Setup → Foundational → **US1（T014-T022）**
2. **STOP and VALIDATE**：quickstart 场景 1/2/6（上传/出处/原文件）
3. 此时已可日常使用（真实资料入库 + 问答）—— 建议尽早开始用真实数据喂养

### Incremental Delivery

1. US1 → 验证 → 日常使用（MVP）
2. US2 → 库外兜底补全体验
3. US3 → 闭环成立（越用越聪明）
4. US4 → 双端安装体验
5. Polish → 备份（T031 建议尽早做，防数据意外）/ 验收 / 安全 / 上线

### 关键提醒

- **T031 备份**虽然排在 Polish，但只依赖 Phase 2 —— 一旦有真实资料入库就应尽快执行（constitution VI）
- 每个 Checkpoint 停下来验证再继续（spec 的验收场景为准）

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签映射 spec 的 user story（US1~US4），可独立验收
- 每个任务完成后勾选 `- [x]` 并对照 DoD 验证（/speckit-implement 依据）
- 避免：含糊任务、同文件冲突、跨 story 破坏独立性的依赖
