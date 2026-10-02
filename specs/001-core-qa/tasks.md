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

- [x] T001 创建项目骨架：`server/`（pyproject.toml + app/ 包）、`web/`、`deploy/`、`.env.example`
  - Deps: 无
  - DoD: 目录结构与 plan.md「Project Structure」一致；`pip install -e server`、`npm install --prefix web` 可执行
- [x] T002 [P] Postgres 16 + pgvector 容器：`deploy/docker-compose.yml`（db 服务）
  - Deps: T001
  - DoD: `docker compose up -d db` 后 `CREATE EXTENSION vector` 成功
- [x] T003 [P] FastAPI 骨架：`server/app/main.py`（`/health` + pydantic-settings 配置加载）
  - Deps: T001
  - DoD: `uvicorn` 启动成功，`GET /health` 返回 200
- [x] T004 [P] Next.js 骨架：`web/`（App Router、`output: 'export'`、基础布局）
  - Deps: T001
  - DoD: `npm run build` 产出 `web/out` 静态文件
- [x] T005 [P] 代码质量工具：ruff（server）+ eslint/prettier（web）
  - Deps: T001
  - DoD: lint 命令可执行且通过空项目检查

**Checkpoint**: 前后端骨架可构建、数据库可启动

---

## Phase 2: Foundational（阻塞性基础）

**Purpose**: 所有 user story 的共同前提

**⚠️ CRITICAL**: 本阶段完成前，任何 user story 不可开始

- [x] T006 数据模型：`server/app/models/`（users / documents / chunks / conversations / messages，**全表带 owner_user_id**）
  - Deps: T003
  - DoD: 字段与 data-model.md 逐项一致（含 status/source_type 枚举、citations jsonb、sha256 判重字段）
- [x] T007 数据库迁移：`server/alembic/`（建表 + pgvector 扩展 + HNSW 索引 + FTS 索引）
  - Deps: T002, T006
  - DoD: `alembic upgrade head` 建出全部表与索引；`downgrade base` 可回滚
- [x] T008 认证边界：`server/app/auth/`（单用户白名单单账号，argon2 + HttpOnly 会话 Cookie + 全 API 守卫）
  - Deps: T003, T007
  - DoD: 未登录访问任一 `/api` 端点返回 401；登录后放行；账号来自 `.env` 初始化（constitution VII）
- [x] T009 [P] 原文件存储抽象：`server/app/storage/`（本地磁盘实现，`storage/{owner}/{doc}` 分区 + sha256 工具）
  - Deps: T003
  - DoD: 存/取/删与 sha256 校验测试通过；接口为抽象基类（可替换）
- [x] T010 [P] Embedding provider：`server/app/ingestion/embedding.py`（默认硅基流动 bge-m3，`.env` 可切百炼）
  - Deps: T003
  - DoD: 文本 → 1024 维向量；provider 通过配置切换，接口可替换
- [x] T011 [P] 对话模型客户端：`server/app/chat/llm.py`（DeepSeek 默认、`.env` 可切；流式接口）
  - Deps: T003
  - DoD: 逐 token 流式输出可用；异常可捕获（供降级路径使用）
- [x] T012 静态托管：`server/app/main.py`（挂载 `web/out` + SPA 回退，`/api` 优先）
  - Deps: T004
  - DoD: 浏览器访问 `:8000` 打开前端；未知路径回退 `index.html`
- [x] T013 测试脚手架：`server/tests/`（pytest + 独立测试数据库 fixture）
  - Deps: T007
  - DoD: `pytest` 可运行（含测试库自动建/清）

**Checkpoint**: 骨架就绪，user story 实现可以开始

---

## Phase 3: User Story 1 - 上传资料并基于内容问答 (P1) 🎯 MVP

**Goal**: 上传文档 → 解析入库 → 提问得到**带出处**的回答

**Independent Test**: 上传一份含明确内容的文档 → 提一个只有该文档能回答的问题 → 回答正确且出处指向该文档

- [x] T014 [US1] 上传端点：`server/app/documents/router.py`（multipart、sha256 判重 FR-001、登记 processing、存原文件）
  - Deps: T008, T009
  - DoD: 201 `{id,status}`；相同内容返回 200 duplicate（契约符合 contracts/api.md）；超过单文件上限（默认 200MB）时拒绝并明确提示
- [x] T015 [US1] Docling 解析管线：`server/app/ingestion/parser.py`（PDF/EPUB/TXT/MD/DOCX；扫描件/损坏 → unparseable + 原因，FR-014）
  - Deps: T013, T014
  - DoD: 文本型 PDF 解析出带标题路径的文档树；扫描版 PDF 判定 unparseable 且保留登记
- [x] T016 [US1] 分块 + embedding 入库：`server/app/ingestion/pipeline.py`（HybridChunker → heading_path/page/chapter 入 chunks）
  - Deps: T010, T015
  - DoD: 样例书产出 chunks（含 heading_path 与 page）；status→indexed；SC-001 计时（300 页内 <5 分钟）
- [x] T017 [US1] 后台任务执行器：`server/app/ingestion/tasks.py`（进程内异步 + reprocess 端点）
  - Deps: T016
  - DoD: 上传立即返回、解析后异步完成；`POST /api/documents/{id}/reprocess` 可重试
- [x] T018 [US1] 资料管理端点：`server/app/documents/router.py`（列表——仅 source_type=upload，FR-009 / 原文件下载 FR-013 / 删除级联 FR-003+011）
  - Deps: T008, T009
  - DoD: 下载文件 sha256 与上传件一致（SC-006）；删除后 chunks 与原文件同步消失；列表接口仅返回上传来源的资料（过滤条件正确）
- [x] T019 [US1] 混合检索：`server/app/retrieval/search.py`（pgvector + FTS + 相关度分数；可替换接口）
  - Deps: T007, T016
  - DoD: 语义相近的提问命中正确 chunk；返回含 document/chunk 元数据与分数
- [x] T020 [US1] 对话端点（命中分支）：`server/app/chat/router.py`（编排含会话历史上下文，FR-004 + SSE：meta/token/done/error）
  - Deps: T011, T019
  - DoD: 命中时 `meta.citations` 含 资料名+位置+引用片段（FR-006）；事件序列符合 api.md；多轮追问可结合上文理解（如"那本书里怎么说的"指代明确）
- [x] T021 [US1] 前端-资料页：`web/app/`（登录页 + 上传进度/状态/列表/下载/删除）
  - Deps: T012, T018
  - DoD: 浏览器完成 上传 → 看到 indexed → 下载 全流程
- [x] T022 [US1] 前端-对话页：`web/app/chat/`（SSE 渲染 + 出处展示：正文 [N] 内联可点击跳转 + 底部出处列表：资料名/位置/可展开引用片段）
  - Deps: T012, T020
  - DoD: 提问书中细节 → 流式回答 + 出处可见（quickstart 场景 2 手工通过）；正文 [N] 编号为可点击跳转按钮（底部列表为编号对照，不再重复放按钮）；引用指向已删除资料时显示"来源已删除"且不报错（T028 复用同一渲染组件）
- [x] T036 [US1] 在线浏览原文件（FR-015，2026-10-01 增补）：后端 inline 下载参数 + 单文档端点；前端 `/view/` 浏览页（PDF 内置阅读、EPUB 渲染、文本视图）
  - Deps: T018, T021
  - DoD: 资料列表点"浏览"→ 浏览器内直接查看 PDF/EPUB/TXT/MD 原文件；无法解析的 PDF 同样可浏览；其他格式提示下载；EPUB 阅读进度显示真实百分比
- [x] T037 [US1] 出处跳转原文位置（FR-016，2026-10-01 增补）：对话答题的出处链接 → `/view/?id=&page=&q=&from=chat`；PDF 翻页、文本高亮定位、EPUB 精确定位（CFI 到引文页 + 引文高亮，逐级退回"章节 → 开头"）；从对话进入可"返回对话"；已删资料提示
  - Deps: T022, T036
  - DoD: 点击回答中的出处 → 打开原文件并跳到对应位置（PDF 页、文本高亮、EPUB 引文页 + 黄色高亮）；从对话进入时"返回"回对话页；资料已删除时显示"来源已删除"提示
- [x] T039 [US1] 检索查询改写（FR-004 多轮上下文增强，2026-10-01 增补）：指代性追问（"这本书/它/刚才"等）拼上一轮问题做检索
  - Deps: T020
  - DoD: 指代性追问能命中正确资料并给出出处（已实测："它主要面向什么读者"命中目标书）

- [x] T041 [US1] PDF 文本层快通道（R7，2026-10-01 事故复盘补）：`server/app/ingestion/pdf_fast.py`（pypdfium2 直抽 + 段落/断词/页眉页脚/字号标题启发式 + 表格占比检测）
  - Deps: T015
  - DoD: 1240 页 PDF 全流程（含 embedding）<5 分钟、峰值内存 <500MB（实测 49s / 133MB）；标题与页码入 chunk；无文本层 → unparseable（FR-014 不变）
- [x] T042 [US1] 解析进度与中断恢复（R7）：批次间进度写 status_reason（"解析中 x/y 页"→"索引中 x/y 块"）；启动扫尾把中断的 processing 标记"可重试"
  - Deps: T017
  - DoD: 界面可见解析进度；服务重启后卡死文档显示"上次解析被中断…点重试"（实测通过）
- [x] T043 [US1] 深度解析与表格提示（R7）：Docling 分页批处理（120 页/批、默认关 OCR）+ `reprocess?mode=deep` + 表格占比 ≥8% 时 parse_hint 与「深度解析」按钮
  - Deps: T041
  - DoD: 深度解析内存受控、批次间可释放；表格多的书自动出现提示按钮（本书 3.7% 不触发）；深度解析后 hint 清除

- [x] T044 [US1] 上传与解析进度条（2026-10-01 增补）：上传改用 XHR 上报进度（fetch 不暴露上传进度）；解析/索引进度结构化（status_reason 提取为 API progress 字段）驱动前端进度条
  - Deps: T042
  - DoD: 上传显示百分比进度条；解析（深度模式"x/y 页"）与索引（"x/y 块"，实测 3046 块逐批推进）显示确定进度条；无数字阶段显示不确定动画

**Checkpoint**: US1 独立可用 —— **MVP 达成**，可开始真实使用与验收

---

## Phase 4: User Story 2 - 库外问题由外部模型兜底 (P2)

**Goal**: 库中无相关内容时兜底回答，并明确标注来源类型

**Independent Test**: 空库/库外问题提问 → 得到回答且标注"来自模型知识"

- [x] T023 [US2] 检索判定与兜底分支：`server/app/chat/orchestrator.py`（阈值判定 → model_knowledge + related_hints，FR-007；元数据匹配：提问涉及"无法解析"文件（按文件名匹配）时，告知其存在但内容暂不可读，FR-014）
  - Deps: T020
  - DoD: 库外问题走兜底并标注来源；弱相关附"库中可能相关"提示且不混入主回答；问及无法解析文件时得到"有此文件、内容暂不可读"的明确回复（与资料列表可互相核对）
- [x] T024 [US2] 模型故障降级：`server/app/chat/`（error 事件 + 可重试，不影响历史与资料）
  - Deps: T023
  - DoD: 断开模型 API 后提问得到明确错误；恢复后重试成功
- [x] T025 [US2] 前端：来源类型标注 + "库中可能相关"提示 UI：`web/app/chat/`
  - Deps: T023
  - DoD: "模型知识"标注清晰可辨；弱相关提示可展开查看
- [x] T038 [US2] 对话 token 用量记录与展示（FR-017，2026-10-01 增补）：LLM 客户端请求 include_usage；messages.usage 落库（tokens + 估算费用）；done 事件携带；回答下方小字展示
  - Deps: T020
  - DoD: 每轮回答下方显示 ↑输入 ↓输出 tokens 与 ≈¥ 估算金额；messages.usage 非空（库中可查）；金额按 .env 单价可配置

**Checkpoint**: US1 + US2 均独立可用

---

## Phase 5: User Story 3 - 兜底问答回写闭环 (P3)

**Goal**: 兜底问答入库；二次提问命中"既往对话"

**Independent Test**: 问库外问题 → 再问同一问题 → 第二次来自库且无新模型调用

- [x] T026 [US3] 回写管线：`server/app/chat/writeback.py`（问答对 → source_type=conversation，分块 + embedding，FR-008）
  - Deps: T010, T023
  - DoD: 兜底完成后问答入库且可被检索；回写失败不阻塞用户回答
- [x] T027 [US3] 二次命中标注 + 对话历史端点：`server/app/conversations/router.py`（prior_conversation；列表/消息/删除 FR-009+011）
  - Deps: T026
  - DoD: 重复提问命中既往对话且无新模型调用（SC-004）；删除对话生效
- [x] T028 [US3] 前端-对话历史：`web/app/`（侧栏：列表/查看/删除）
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

- [x] T031 备份机制（2026-10-01 决策调整；本地部分 2026-10-02 完成）：`deploy/backup/` —— 本地每日 pg_dump + **客户端加密** + 原文件镜像 + 保留策略 + 恢复脚本；异地对象存储同步**延后至部署阶段**（T035，与服务器同厂同地域，rclone 仅作传输、密文上传，见 R8）
  - Deps: T007, T009
  - DoD（本地部分）：定时产出加密备份；恢复演练 1 次通过（**含解密链路**）；删除的内容不再进入后续备份（验收含抽查）；异地副本随 T035 一并验收（SC-008 完整判定在部署后）
  - 完成记录（2026-10-02）：cron 两条已装并经核验（每日 03:17 + @reboot，STALE_ONLY 实跑跳过 ✓）；演练多轮全绿（最新 db-20261002-0004，行数/消息指纹/文件 sha256 三项一致）；密钥已交接用户离线保管；删除同步经核验（rsync --delete 生效）
- [x] T040 [US1] SC-002 样例题集与通过率评测（2026-10-01 analyze 补）：`server/tests/acceptance/questions.yaml`（≥20 题：问题 + 标准答案要点 + 出处对照）+ 评测脚本输出通过率
  - Deps: T019, T020
  - DoD: 题集 ≥20 题（含中文/英文、命中/兜底/二次命中三类）；评测脚本一键跑批，输出"库内作答率与出处正确率 ≥80%"报告
  - 完成记录（2026-10-02）：题集 22 题（命中 15 / 兜底 5 / 二次命中 2，含 2 道英文）；实测 **命中 13/15=87%（PASS）**、兜底 5/5、二次命中 2/2；报告落盘 `tests/acceptance/sc002_report.json`；脚本带**自清理**（跑完删除评测对话及其回写，防语料污染）；遗留观察：2 例跨语言查询未达命中阈值（g05/g06）→ 列入检索调优（R9 未决项）
- [x] T032 [P] 验收脚本：`server/tests/acceptance/`（quickstart 场景 1-9 自动化）
  - Deps: T022, T027, T029, T031
  - DoD: `pytest tests/acceptance/` 全绿（覆盖 SC-001~008；SC-002 样例题集与评分见 T040）
  - 完成记录（2026-10-02）：**6 过 1 跳 101 秒全绿**（场景 1/3/4/6/7 自动化 + SC-002 包裹评测 + SC-008 包裹演练；场景 7 安装为手动 skip）；HTTP 端到端打真实服务、服务不可达整套 skip、用例自清理；**顺带修复演练设计缺陷**（drill 现在先做新鲜备份再对照，避免正常写入导致误报失败）；覆盖映射见 `tests/acceptance/README.md`
- [x] T033 [P] 中文 FTS 落地与检索调优：`server/alembic/` + `server/app/retrieval/`（pg_trgm——zhparser 不可用于官方镜像，R9）
  - Deps: T019
  - DoD: 中文关键词检索可用；混合检索权重可配置；性能抽测记录（10 万级检索响应、回答首字 <10s）
  - 完成记录（2026-10-02）：trgm GIN 索引 + 权重配置化；压测 10 万级 ≥3字 0.06–0.37ms / 真·最差（2字扫描）626ms；端到端首字 0.82s；复跑脚本 `server/tests/perf/pg_keyword_bench.sh`（R9）
- [x] T034 [P] 安全加固：`deploy/` + `server/app/auth/`（登录限速、HTTPS/Caddy 部署说明、密钥清单）
  - Deps: T008
  - DoD: 登录限速生效；部署文档含 HTTPS 完整步骤
  - 完成记录（2026-10-02）：登录限速（5 次/15 分钟，实测 5×401→429+Retry-After，按 IP+用户名隔离，可配置）；`deploy/SECURITY.md`（密钥清单 + HTTPS 完整步骤 + 部署核对清单）；Cookie `secure` 配置化（AUTH_COOKIE_SECURE）
- [ ] T035 部署上线：`deploy/`（生产 compose + 服务器初始化文档，2C4G + Caddy + 自启）
  - Deps: T031
  - DoD: 一台全新服务器按文档 30 分钟内跑起可访问的 PWA（对照 quickstart 逐项）
  - 进度（2026-10-02）：**部署工件就绪**——`deploy/deploy.md`（30 分钟初始化手册，venv+systemd+Caddy 形态）、`second-brain.service`（自启/崩溃重拉/最小权限）、`Caddyfile`（自动 HTTPS）；compose 加固（DB 仅绑 127.0.0.1、密码走 deploy/.env）。**实机验收待服务器租用后执行**（用户决定延后，届时跑 `pytest tests/acceptance/` 核对）

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

## 2026-10-02 试用增强补记（as-built，用户驱动）

> 规则审计补记：以下为实施后补录的任务项（先实现后补记），均含 DoD 与测试证据。

- [x] **T046 列表分页/搜索/排序（FR-018）**：服务端 `GET /api/documents` 信封化 + `q/sort/page/page_size`（正文子串复用 trgm 索引；真机 ~20ms）；前端工具条/页码条/URL 状态/命中片段与高亮
  - DoD: `tests/test_documents_list.py` 5 例；真机数据分页/排序/正文命中验证 ✓
- [x] **T047 对话全文搜索 + 侧栏收起（FR-019）**：`GET /api/conversations/search` + `ix_messages_content_trgm`（迁移 `d51a9c73e2b4`）+ MCP 共用核心（003）；前端搜索/定位/高亮/收起（Ctrl+B、状态记忆）
  - DoD: `tests/test_conversations_search.py` 5 例；真实库会话级结果/大小写/排序验证 ✓
- [x] **T048 深浅双模式**：`light-dark()` + 手动覆盖（localStorage）+ 首屏内联脚本
  - DoD: 构建通过；亮/暗/跟随系统三态；无首屏闪跳 ✓
- [x] **T049 对话页 ChatGPT 风格重做 + 引用 chip 修复**：平铺式消息/组合输入框/空状态/复制按钮/流式光标；`urlTransform` 放行 `citation:` 协议
  - DoD: 构建通过；引用 chip 渲染脚本级验证（research R11/R12）✓
- [x] **T050 既往对话引用的来源追溯（FR-020）**：`app/chat/inherit.py`（resolve + enrich）；检索层携带 conversation_id；orchestrator 生成时富化 + 消息读取时存量富化；前端 [N] 继承映射 / 「回到原对话」深链 / 「原对话出处」列表
  - DoD: 单测 +4（直接继承/复制型向前追溯/无法匹配降级/存量富化）；真实链路复现验证（原报问题消息读取即补全 3 个原始出处）✓
- [x] **T051 检索融合修正（R15）**：关键词加成限定向量候选 + boost 0.05→0.12 + 候选池 ×3
  - DoD: 59 单测全过；目标查询实测条目 0.593→0.713/0.685 过线；端到端回答正确列出 2 个项目 ✓
- [x] **T052 低置信多查询重试（FR-021/R19）**：`app/retrieval/rewrite.py`（变体扩写）+ orchestrator 合并检索（仅无强命中触发；失败静默）
  - DoD: 单测 +6（解析/上限/去回显/失败空/编排救回/强命中跳过）；实测救回（0.53→0.736）；接线验证（弱查询触发 + 日志、强查询不触发、回答优雅降级）；拜占庭验收题变体 ≤0.518 无假强命中 ✓
- [x] **T053 回写守卫变体扩展 + 「关于我」笔记处理（2026-10-02）**：守卫标记补「看不到你 / 无法看到 / 没有关于你」等（含单测）；「关于我」笔记曾建→段落化重建→**按用户决定撤销**（数据补丁移除；该问句类改由扇出承担——概率性，见 R19 备注）
  - DoD: `test_writeback_guard` 扩充通过；撤销后带名字问法（「Jason L 的技术栈」）稳定命中 profile ✓；裸问句不稳定已如实记录 ✓

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签映射 spec 的 user story（US1~US4），可独立验收
- 每个任务完成后勾选 `- [x]` 并对照 DoD 验证（/speckit-implement 依据）
- 避免：含糊任务、同文件冲突、跨 story 破坏独立性的依赖
