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
  - 补记（2026-10-03，用户验收）：底部来源列表改为**按类别分组 + 各组默认折叠**——「网络来源 / 出处」（`msg.citations` 按 `web` 拆分，编号保持与正文 [N] 对照不变，混合回答此前统一标「网络来源」的问题一并修正）、「原文出处」（继承来源，原「原对话出处」更名）、「库中可能相关」；摘要行显示「类别 + 条数」，点开才列条目；网络来源条目标题为直链（2026-10-03 同日，见 004 T011 补记）
- [x] T036 [US1] 在线浏览原文件（FR-015，2026-10-01 增补）：后端 inline 下载参数 + 单文档端点；前端 `/view/` 浏览页（PDF 内置阅读、EPUB 渲染、文本视图）
  - Deps: T018, T021
  - DoD: 资料列表点"浏览"→ 浏览器内直接查看 PDF/EPUB/TXT/MD 原文件；无法解析的 PDF 同样可浏览；其他格式提示下载；EPUB 阅读进度显示真实百分比
  - 补记（2026-10-03，用户实测）：① 键盘 ←→ 在章内焦点失效——epubjs 章节为独立 iframe、window 监听收不到章内按键 → 注册到每章 content hooks 修复（窗口监听保留为兜底）；② 新增 EPUB **目录**（`book.loaded.navigation` 递归渲染、点击跳转）与**页码**显示（locations 索引 x/y，估算口径；`generate` 完成前不显示）；③ **按页跳转**（输入框 + Enter/按钮，`cfiFromLocation` 定位，页码口径与显示一致、越界钳制；输入框聚焦时 ←→ 不触发翻页）——spec FR-015 已增补 ✓
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
  - 补记（2026-10-03）：列表更名「**原文出处**」并纳入底部来源分组折叠（默认折叠、摘要行显类别+条数，见 T022 补记）
  - 追记（2026-10-03，用户实测两轮）：①修复「在 /chat/ 内点击对话类引用无反应」——同路由软导航不重挂载、挂载期一次性深链解析不会重跑；②用户反馈"直接整页跳转太突兀"→ 定为**对话引用预览小窗**（ConvPreview）：点对话类 [N] 角标弹出只读小窗（消息流 + 自动定位高亮被引用消息、Esc/点击遮罩/✕ 关闭、窗内引用可续追、书籍类引用走阅读器），窗内「↗ 在对话中打开」与「原文出处」列表的「回到原对话」按钮走直接切换会话 + `router.replace` 同步 URL（href 保留：中键/新标签仍走深链）
  - DoD: 单测 +4（直接继承/复制型向前追溯/无法匹配降级/存量富化）；真实链路复现验证（原报问题消息读取即补全 3 个原始出处）✓
- [x] **T051 检索融合修正（R15）**：关键词加成限定向量候选 + boost 0.05→0.12 + 候选池 ×3
  - DoD: 59 单测全过；目标查询实测条目 0.593→0.713/0.685 过线；端到端回答正确列出 2 个项目 ✓
- [x] **T052 低置信多查询重试（FR-021/R19）**：`app/retrieval/rewrite.py`（变体扩写）+ orchestrator 合并检索（仅无强命中触发；失败静默）
  - DoD: 单测 +6（解析/上限/去回显/失败空/编排救回/强命中跳过）；实测救回（0.53→0.736）；接线验证（弱查询触发 + 日志、强查询不触发、回答优雅降级）；拜占庭验收题变体 ≤0.518 无假强命中 ✓
- [x] **T053 回写守卫变体扩展 + 「关于我」笔记处理（2026-10-02）**：守卫标记补「看不到你 / 无法看到 / 没有关于你」等（含单测）；「关于我」笔记曾建→段落化重建→**按用户决定撤销**（数据补丁移除；该问句类改由扇出承担——概率性，见 R19 备注）
  - DoD: `test_writeback_guard` 扩充通过；撤销后带名字问法（「Jason L 的技术栈」）稳定命中 profile ✓；裸问句不稳定已如实记录 ✓
- [x] **T054 查询规划器（FR-022/R21）**：`app/chat/planner.py`（三工具 + 解析/上限/容错）+ orchestrator 执行与组装（编号连续/混合引用/回退基线）；四套句式路由一体删除（意图词表/显式联网正则/websearch 决策器）
  - DoD: 单测（planner 4 例 + 编排 9 例重写）；真机探针 9 类问句全对；`app/websearch/planner.py` 与旧测试删除 ✓
- [x] **T055 非语言性垃圾块根治（R17 闭环）**：入库侧 `app/ingestion/quality.py`（语言字符比 < 0.5 不索引，含单测）；存量清理**已执行**（用户授权，2026-10-03：删除 8493 块，文档保留，REINDEX+VACUUM 后零残留）
- [x] **T056 验收重校准**：重选「光合作用」题（零语义钩子，4/4 稳定兜底）；全量验收 11 通过 / 1 跳过 ✓
  - Deps: T055
- [x] **T057 回写守卫 LLM 化 + 时间词表退役（R18 续三/R21 续，2026-10-03）**：`is_reusable_qa` 语义判定替代 15 条标记词表（编造型自此可捕获）；`_TEMPORAL_HINTS`/`looks_temporal` 删除（工具化后预检无用）
  - DoD: 单测 3 例（是/否/失败保守跳过）；真 LLM 探针 5/5；端到端（知识回写 ok、寒暄零回写）；103 单测全过 ✓
- [x] **T058 指代拼接降级为低置信候选（T039 改造，2026-10-03）**：`_retrieval_query` 前置改写 → `_referential_splice` 仅作重试候选；修复"短新问题被旧话题稀释"（实测 0.624→0.594 跌破阈值）
  - DoD: 单测 +3（规则/强命中零拼接/弱追问拼接救回）；真机 A/B 场景验证；106 单测全过 ✓
- [x] **T059 指代消解交规划器——词表终极退役（R21 续三/R3 补记，2026-10-03）**：`plan_retrieval` 携带最近 3 轮对话窗口 + 改写指令（conversational query rewriting 行业范式）；`_REFERENTIAL_HINTS` 与 `_referential_splice` 整体删除
  - DoD: 探针 4/4（指代/省略/序数/无上下文不编造）；端到端 B 场景翻盘（追问完整答出书中内容）；隐私分析入 R3 补记（同源零新增暴露、FR-006 不变）；104 单测全过 ✓
  - 验收追记（同日）：规划器补"内容/清单边界"与"历史不越权"两条判据（R21 续三·追记）——sc007 组合问句循环 10/10；全量验收 11 通过 / 1 跳过 ✓
- [x] **T060 页面操作栏吸顶（2026-10-03 试用反馈）**：顶栏（`.header`）全局吸顶；其下操作条按实测高度对位停靠——资料页页签行（`.actions-sticky`）、阅读页 EPUB 工具栏（`.view-toolbar`）；吸顶高度由 `HeaderOffset` 组件实测写入 `--hdr-h`（移动端顶栏换行自适应，不写死像素）；顺带：来源列表按类别分组折叠（网络来源/出处/原文出处，见 T022/T050 补记）、网络来源标题直链（见 004 T011 补记）。覆盖 `/`、`/view`、`/snap`
  - DoD: 前端构建通过 ✓；滚动长列表/长文时顶部按钮常驻（用户真机复核）
  - 追记（同日，用户实测）：对话页侧栏"吸顶"方案引入遮挡（侧栏伸至视口底部、盖住全宽发消息栏）→ 该页改为 **ChatGPT 式外壳**：壳高 100dvh、侧栏与主列并排各自独立滚动、消息区独立内滚（768 居中列，`padding-inline: max()` 技巧）、发消息栏为主列内底栏（不再 fixed、不再压内容）——**结构上不可能再被遮挡**；滚动位置记忆/贴底跟随/跳转定位由 window 迁移至消息区容器；侧栏移动端保持原有横向会话条。同轮（用户要求"与 ChatGPT 一致"，先查证 ChatGPT 设计规范再落地）：顶栏/侧栏顶部按钮 ChatGPT 化——**ghost 无边框、10px 圆角、悬停 5% 淡色填充（"chrome should recede until hovered"）、组内 6px 间距（`hdr-actions` 改 flex 消除基线错位）、图标钮 36×36**；收起钮按 ChatGPT 排布移入**侧栏顶部行**（[◀ 收起] [＋ 新对话] 并排），侧栏收起时顶栏出现 ▶ 展开钮；「＋ 新对话」由主色填充改为 ghost 行。规范来源：refero.design ChatGPT 样式拆解（10px 圆角/5% 悬停淡色/6px 节奏）。另（用户要求）：消息区滚动策略改为**仅「发送 / 打开会话」时定位一次到底部、流式生成期间完全不跟随**——不再被拽到回答底部，页面保持不动（原"贴底 140px 阈值自动追随"逻辑整体删除；跳转定位/历史位置恢复优先级高于一键到底）。再另（同日）：对话页外壳改**全宽**——去 1100px 居中容器，侧栏 260px 贴左缘全高、内容列在剩余区域居中、顶栏左右 16px 留白（修复宽屏下内容被挤在中间）；按钮补 `font-family: inherit`（`<button>` 默认不继承页面字体——「对话（链接） vs 退出（按钮）」字形不一致的根因）
- [x] **T061 范式审计一期整改：文实不符 2 项（2026-10-03，全项目审计驱动）**：①Docling 分块对齐 R5——`HierarchicalChunker()`（零参数，超长块超 embedding 上限）→ `HybridChunker` + bge-m3 tokenizer + `max_tokens=1024`（新增 `transformers` 依赖）；②`quality.py` docstring「<0.4」与代码 0.5 不一致 → docstring 对齐。审计全文与后续批次见 `audit-paradigm-gap-2026-10-03.md`
  - DoD: 分块链实测（标题路径保留 ✓；超长段切分 1008≤1024 tokens ✓）；104 单测全过 ✓
- [x] **T062 计费口径修正（审计二期·R22，2026-10-03）**：`estimate_cost_cny` 改官方**三档分价**（缓存命中/未命中分开）+ **峰谷倍率**（北京时间周一至五 9-12/14-18；法定节假日未建模、按高峰计略高估）；config 计价键替换为 `price_input_hit/miss_per_million` + `price_output_per_million` + `price_peak_multiplier`（deepseek-flash 空闲 ¥0.02/¥1/¥4、倍率 2——旧值 1.1/4.4 无来源且与默认模型错配）
  - DoD: 单测 +4（分档/倍率/缺字段兜底/异常钳制）✓；108 单测全过 ✓；定价来源入 research R22 ✓
- [x] **T063 审计二期·会话加固 + fail-closed（R23①②，2026-10-03）**：签名 SHA-1→SHA-256；`users.session_epoch`（迁移 70eda961aa20）+ cookie 携纪元、**登出纪元 +1 → 全设备失效**（无状态 cookie 的服务端吊销）；登录 dummy 校验防枚举时序；argon2 参数显式固化（t=3/m=64MiB/p=4，RFC 9106 低内存档）；SECRET_KEY/ADMIN_PASSWORD 哨兵默认值 → **启动拒绝**（fail-closed）；cookie Secure 按环境自动
  - DoD: 单测 +4（纪元匹配/失配 401/登出后旧 cookie 失效/assert_secure 拒绝）✓；114 单测全过 ✓；迁移已应用 ✓
  - 实启发现（同日）：fail-closed **上线首启即拦截真实占位配置**——`.env` 的 SECRET_KEY 与 ADMIN_PASSWORD 一直就是哨兵默认值（此前无检查所以从未暴露）。已更换为强随机值（同时更新库内口令哈希）；真机冒烟：登录 204 → /api/me 200 → 登出 204 → 旧 cookie 401 → 重登 200 ✓；全员旧会话已失效（签名升级 + 密钥更换），需用新口令重新登录
- [x] **T064 审计二期·写回最小对齐（R23③，2026-10-03）**：写前近似查重（新问答 embedding 与 owner 全库最近邻相似度 ≥0.95 → 跳过回写）；「保持原文形态、无衰减、无冲突处理」登记为显式产品决策（research R23）
  - DoD: 单测 +2（重复跳过/不同内容正常写入）✓；114 单测全过 ✓
- [x] **T065 检索二段式重排（R24/A 方案，2026-10-03）**：新增检索评测工具 `tests/acceptance/retrieval_eval.py`（20 题 × 5 方案：hit@6/MRR/分离间隔，报告落盘）与基线；`hybrid_search` 接入 cross-encoder（bge-reranker-v2-m3 @ 硅基流动，与 embedding 同源 key）复评候选池——重排分即最终分、失败静默降级余弦+加成、`rerank_enabled` 可开关；0.60/0.50 阈值沿用（实测落于 0.377–0.77 分离间隔内）；单测不触外部 API（conftest 总开关）
  - DoD: 评测分离间隔 −0.05 → **+0.39** ✓；单测 +3（替换/降级/禁用）✓；117 单测全过 ✓；真机冒烟：书内问题 kb 命中（6 出处）+ 库外问题正常兜底 ✓；SC-002 回归 PASS（命中 15/15，无回退、r01 修复）✓
- [x] **T066 界面中英切换（FR-023/R25，2026-10-03 用户需求）**：轻量自实现 i18n（零依赖）——`web/lib/i18n.tsx`（LangProvider/`useLang`/`t()` + 非 React 模块 `translate()`；zh/en 双字典，键不一致编译期报错）；顶栏主题钮旁 `LangToggle`（显示目标语言 EN/中）；localStorage 记忆（`sb-lang`）+ 首次跟随浏览器语言；静态导出首帧中文（与 HTML 一致，hydration 安全）、挂载后同步；`<html lang>` 同步更新。覆盖全部界面：资料库（存储行/排序项/采集凭据/清理区）、对话页、阅读器（目录/跳页/引文定位提示）、快照、登录 + 通用组件（分页/工具条/主题钮）+ `lib/api.ts` 客户端错误兜底（经 `translate()` 读取同一记忆）。view 页 effects 经 `tRef` 取文案——语言切换不重跑加载、不丢 EPUB 阅读位置
  - DoD: `tsc --noEmit` 0 错 ✓；`eslint` 0 问题 ✓；`npm run build` 静态导出通过 ✓；全量 grep 核查无未翻译的用户可见中文（i18n 字典/代码注释除外）✓；真机复核（用户）
  - 范围排除（按批准）：回答内容（模型按提问语言作答）、后端错误消息、layout 静态 metadata description（保持中文）
- [x] **T078 生成过程状态行（2026-10-03 用户需求）**：后端流水线各阶段发 `status` 事件（`planning`/`retrieving`/`listing`/`expanding`/`web_search`/`generating`；`prepare_reply` 增 `on_status` 回调、路由经 asyncio 队列即时转发——覆盖首 token 之前的规划与取数等待段）；前端流式气泡显示 阶段文案 + 实时用时（1s tick）+ 已输出字数，完成后在用量行附「⏱ 用时」（done 回填 elapsedMs）；契约更新（contracts/api.md status 事件）
  - DoD: 120 服务端测试全过 ✓；`tsc`/`eslint`/`npm run build` 通过 ✓；SSE 冒烟 ✓（curl 实测事件序列：`status(planning,retrieving)` → `meta` → `status(generating)` → 279×`token` → `done`；冒烟会话已清理）
  - 说明：当前模型（deepseek-flash）不吐思维链，「思考过程」以阶段进度呈现；换推理模型（思考链可见）为独立选型决策
- [x] **T079 费用全成本口径（2026-10-03 用户需求）**：原先只计回答模型 token 费 → 新增 `app/costing.py`（ContextVar 单轮累加器）：LLM 小调用（规划/扩检/时间解析，经 `complete_chat` 自动计入，同分档定价）、联网按次（智谱单价按引擎：std ¥0.01 / 其余 ¥0.05，失败不计费——调用点 `websearch/client.py`）、检索按 tokens（embedding bge-m3 ¥0/M、rerank Qwen3-4B ¥0.14/M——`embedding.py`/`search.py` 调用点，单价入 config）；`done` 载荷与消息 usage 增 `cost_breakdown`，`cost_cny` = 全成本合计；前端费用小字悬停显示分类明细（模型/联网/检索）
  - DoD: 单测 +3（累加器/complete_chat 钩子/无回合上下文静默）✓；123 服务端测试全过 ✓；`tsc`/`eslint`/`npm run build` 通过 ✓；**端到端实测**：联网问题 `cost_cny 0.0133 = llm 0.0033 + web 0.01`、库内问题 `0.0037 = llm 0.0014 + retrieval 0.0023` ✓（冒烟会话已清理）
  - 注记：历史消息为回答单调用口径（语义版本差异）；回写判定/回写 embedding 的后台成本不计入（发生在展示之后）
- [x] **T080 联网"结果不相关"措辞修复（2026-10-03 用户实测事故驱动）**：用户问 Upwork 需求类型——系统**已联网**（3 条网络来源）但结果全是项目管理软件榜单，回答却出现"可以发一条明确的联网指令…我就能按最新网络数据给你答案"的措辞，暗示"尚未联网"、自相矛盾。根因：提示词规则 6 只有"已提供 web_results / 未提供"两支，缺**已提供但不相关**支。修复：SYSTEM_PROMPT 规则 6 补第三支硬约束（如实说明已检索但不相关；通用知识部分明确标注；**不得说"我还没联网/你发联网指令我才能查"**；换关键词重搜表述为"我可以换关键词再搜一次（如…）"）
  - DoD: 123 服务端测试全过 ✓；同题真机复测（措辞含"已检索但不相关"且不再暗示未联网）✓；004 spec FR-011 补记 + acceptance 场景 3 扩边界 + 004 tasks 追记同步 ✓
  - 备注：本例搜索质量本身欠佳（std 引擎对该查询返回榜单类页面）——已由 T081 解决（引擎换 sogou + 结果重排过滤）
- [x] **T081 联网搜索质量修复（R37，2026-10-03 用户实测驱动）**：① 默认引擎 search_std → **search_pro_sogou**（四组查询对照：std/pro 同源偏中文 SEO；sogou 命中真实数据源），fallback → quark；② 结果重排过滤：`_filter_web_results`（复用 cross-encoder 复评「标题+摘要」vs 用户问题；低于 `web_search_relevance_floor=0.3` 剔除、按分排序截断；**全部低相关换备用引擎重试一次**、计入每日护栏；重排失败/关闭 → 原序保留静默降级）；`rerank_texts` 公开接口 + 客户端 `search_with_engine`
  - DoD: 单测 +3（过滤排序/全低换引擎重试/重排失败降级）✓；126 服务端测试全过 ✓；**同题真机复测**：网络来源从"项目管理软件榜单"变为 5 条 Upwork 官方招聘报告、回答引用真实增长数据并如实区分网络/通用知识 ✓（复测会话已清理）；成本明细 `{llm 0.0061, web 0.05, retrieval 0.0022}` ✓
- [x] **T082 搜索+读页：多查询执行与正文提取（R38，2026-10-03 用户对比实测驱动）**：① `_build_web_context` 执行规划器**全部**联网查询（≤3、各自计费与护栏）并按 URL 合并去重；② 新模块 `app/websearch/reader.py`：并行抓取（并发 4/超时 8s/2MB/仅 HTML）→ trafilatura precision 正文提取 → **段落级重排筛选**（≤2000 字/页、≤6 段；重排不可用→截断降级；整体 `reader_max_pages=0` 可关）；引用摘录改自页面正文（失败回退摘要）；新增依赖 trafilatura（uv add）；conftest 增测试期关读页开关
  - DoD: 单测 +4（正文提取去导航/段落筛选/截断降级/抓取失败跳过）✓；132 服务端测试全过 ✓；**同题真机终验**：两条查询全执行（web ¥0.10）、回答引用 2026 官方技能报告具体数据（AI 集成 +178% 等）、引用摘录来自正文、全程 11s（会话已清理）✓
- [x] **T083 联网失败可见性（2026-10-03 用户实测事故驱动）**：**事故**：智谱账户余额不足（错误码 1113）→ 后续联网全部失败、按设计静默降级为通用知识作答——但用户完全不可见，连续两问"咋这都不搜呢"。修复：`ReplyPlan.web_failed`（联网被规划却零结果：供应商失败/额度用尽）→ meta 透出 → 回答来源行附「（联网检索失败，未使用网络来源）」；凭据未配置仍静默（能力关闭≠失败）；FR-004 补记（降级不中断的语义不变、失败事实可见）
  - DoD: 单测（失败降级用例增 web_failed 断言；成功用例断言 False）✓；132 服务端测试全过 ✓；`tsc`/`lint`/`build` ✓
  - 运营备注：智谱（bigmodel）与硅基流动是两家账户——本次为智谱余额耗尽，需充值后再验证
  - **追记（同日二轮，用户实测）**：用户指出 ① 提示未显示**具体原因**（"没有显示智谱余额不足"）；② 更严重——模型把"搜索失败（零结果）"**编造成"已检索但内容不相关"并虚构了结果描述**（"返回的结果主要是 Upwork 介绍页/帮助文档"——实际没有任何结果进入上下文）。三处修复：**a. 原因可见**——供应商错误→原因码映射（`balance`/`ratelimit`/`quota`/`unavailable`），meta 增 `web_error`，前端显示「（联网检索失败：供应商账户余额不足，未使用网络来源）」；**b. 事实基点注入**——`web_failed` 时向模型上下文追加「系统说明：联网检索未成功，本次没有可用的网络结果…不要描述或编造任何搜索结果内容」（同空浏览记录处理的既有模式）；**c. 提示词规则 6 三分支改写**——"已检索但不相关"仅限 **web_results 实际提供**时；带系统说明→如实说检索失败；两者皆无→维持原话术；除①外不得宣称已获得检索结果。真机验证（余额未充）：`web_error=balance` 透出、回答"本次联网检索没能成功…"、零编造 ✓
  - 追记 DoD: 单测 +1（余额→balance 映射）与失败用例扩展（error 码 + 系统说明断言）= 133 全过 ✓；`tsc`/`lint`/`build` ✓
- [x] **T084 时效感知：当前日期注入（2026-10-03 用户实测驱动）**：**事故**：用户问"目前 upwork 需求量最大的软件项目类型"——规划器凭空补出"2025"（日志实锤 `'Upwork 需求最大的软件项目类型 2025'`），搜回旧年度报告；根因=模型不知道"现在"，凭训练记忆猜年份。修复：新增 `today_cn()`（北京时间）；注入两处——① 规划器系统消息（"今天是 {date}……时效诉求类问题的检索词应使用当前年份或 latest，不要凭记忆中的年份"）；② 回答上下文（question_line 与基线路径附"今天的日期是 {date}"，供回答模型判断检索结果时效性——识别过时年度报告并如实说明）
  - DoD: 133 服务端测试全过 ✓；规划器探针 ✓（同问句现输出 `Upwork 2026 需求量最大的软件项目类型` + 英文 2026 变体；另一时效问句同样带 2026）
- [x] **T085 联网检索全自建：SearXNG 部署 + 免费加深（R39，2026-10-03 用户选型）**：deploy compose 增 **searxng 服务**（127.0.0.1:8888、JSON 接口、secret 环境注入）；实机裁剪引擎集 `deploy/searxng/settings.yml`（sogou + bing@cn.bing.com + 360search；其余直连不可用）；新增 `app/websearch/searxng.py` 客户端（`paid=False`：不计护栏/成本）；编排层改"免费加深"——最好分 < 0.45 → 既有扩写器产变体二轮检索合并（默认主源 searxng；`web_search_paid_fallback` 默认关，智谱仅作显式开关）；读页上限 3→4
  - DoD: 139 服务端测试全过 ✓（+SearXNG 客户端解析/免费加深/护栏豁免/付费开关/工厂语义更新）；ruff 触及文件全清 ✓；**真机 E2E（全自建路径）**：联网问答完成、**web ¥0**、总 ¥0.0046（≈20×降）、10s ✓（会话已清理）
  - 运营：SearXNG 随 deploy compose 管理（`docker compose up -d searxng`）；智谱欠费从此不影响联网（付费路径默认关）
- [x] **T086 DeepSeek 服务端搜索接入（R40，2026-10-03 用户驱动）**：新增 `app/websearch/deepseek.py`——官方 Anthropic 兼容端点（`{llm_base_url}/anthropic/v1/messages`）+ `web_search_20250305` 服务端工具；Bearer 复用 `llm_api_key`（零新账号、同一 DeepSeek 账户）；解析 `web_search_tool_result` 块（title/url、多轮去重；密文无摘要 → snippet 空、正文由读页管线补）；token 计费计入 web 成本（`llm.estimate_cost_cny_anthropic` 新增）+ `paid=True` 计每日护栏；`WEB_SEARCH_PROVIDER=deepseek` 生效（缺 key → 能力关闭）；config 增 `DEEPSEEK_SEARCH_{MODEL,TIMEOUT_S,MAX_TOKENS,BASE_URL}` 四项
  - DoD: 单测 +8（deepseek 7：解析去重/请求形状/token 计费/工具错误/HTTP 超时/无搜索块/paid 标记；成本映射 1）✓；**全量 158 通过 / 1 跳过** ✓；ruff 触及文件全清 ✓；**真实 key 冒烟**：13 条结果（Upwork 官方报告在内）、单查询 ¥0.014 ✓；**同题对比评测**：`websearch_provider_eval.py` + 报告 JSON（DeepSeek 3.1–3.6s/≈1 分 vs SearXNG 0.2–0.4s/¥0，质量对照见 R40）✓
  - 备注：**默认源已切至 deepseek**（用户当日确认；config 默认值 + .env，服务已重启）；**真机 E2E ✓**：planning→web_search→generating、5 条 web 引用（Upwork 官方新闻稿/研究页）、`web ¥0.021`＞0（token 计费生效）、总成本 ¥0.0289/轮、会话已清理；服务端搜索为模型轮次（自动改写查询）、时延约为直连源的 10×；评测实证 SearXNG 重排分 0.92–0.99（闸门对门户页盲区——"低分才升级"不适用于 searxng 打底）
- [x] **T067 日期控件替换（R26 追补，2026-10-03 用户实测）**：原生 `<input type="date">` 显示格式随浏览器语言、无法随界面切换（Chrome 官方 FAQ 确认无作者接口）→ 新增 `web/app/_components/date-field.tsx`（业界组件 react-day-picker v10：触发钮按界面语言格式化显示所选日期、弹层日历跟随 zh/en locale、外部点击/Escape 关闭、有值时提供「清除」）；接入 `docs` 页清理区两处（value 契约保持 "YYYY-MM-DD"，后端参数与 UTC 语义不变）；组件与中文 locale 经 `next/dynamic` 按需加载，不进页面首包
  - DoD: `tsc`/`eslint` 0 问题 ✓；`npm run build` 通过、`/` 首包 122 kB（与改造前持平）✓；rdp 样式已入导出 CSS ✓；真机复核（用户）
- [x] **T068 SSE 客户端解析规范化 + 停止/看门狗（R28，2026-10-03 三期 P1）**：手写帧解析退役 → `eventsource-parser`（de-facto 标准，规范处理 CRLF/多行 data/跨块 UTF-8/防缓冲区膨胀）；生成中发送钮变**停止**（AbortController 中止、已生成内容保留）；60s 静默看门狗（**不设总超时**，长回答不掐断）；断流未收 done / 静默超时如实提示（`chat.streamInterrupted`/`chat.streamTimeout`）
  - DoD: `tsc`/`eslint` 0 问题 ✓；`npm run build` 通过（chat 页 50.4→52.1 kB）✓；真机复核（发送/停止/断流，用户）
- [x] **T069 防编造提示词对齐（R27，2026-10-03 三期 P1）**：SYSTEM_PROMPT 规则 1 按 Anthropic 三招补硬约束——事实性内容（数字/日期/人名/结论）以资料原文为准、不得臆测具体值；编号只允许使用本次实际提供的编号、严禁杜撰来源名；模型补充或推断须明确标注
  - DoD: 131 服务端测试全过 ✓；真机问答抽查（用户）
- [x] **T070 SW 缓存策略分级（R29，2026-10-03 三期 P1）**：`/_next/static/*`（内容哈希）缓存优先；未哈希静态（图标/manifest/字体）改 **stale-while-revalidate**（先用缓存、后台刷新）；API 与页面导航始终走网络（现状正确，保留）；缓存版本 v2（旧缓存 activate 清理）
  - DoD: 构建通过、sw.js 随导出产物发布 ✓；真机（图标更新收敛性，随 PWA 日常使用观察）
- [x] **T071 备份加密固化与轮换成文（R30，2026-10-03 三期 P1）**：`backup.sh` S2K 参数显式固化（`--s2k-mode 3 --s2k-digest-algo SHA256`，防工具默认漂移）；README 新增「加密参数与密钥轮换」节（事件轮换流程/旧密钥保留期/存放纪律/演练节奏）
  - DoD: 新参数备份 + `restore.sh drill` 全量对照通过（users/documents/chunks/conversations/messages 行数、消息内容指纹、全量文件 sha256 均一致）✓
- [x] **T072 内容指纹决策登记（R31，2026-10-03 三期 P1）**：保留 FNV-1a 32 位——论证入 R31（单 URL/10 分钟窗口/表上限 500 → 误判 ≈2⁻³² 且失败安全；simhash 为近似去重语义，不匹配"内容相同才跳过"）；无代码改动
- [x] **T073 溯源写时留痕（R32，2026-10-03 三期 P1）**：`chunks.provenance`（JSONB，迁移 `b3f7c2a91d04`）+ 回写时解析存储（源消息 id 已知，跳过匹配）+ 读取零匹配取用 + 存量回填脚本（`scripts/backfill_chunk_provenance.py`，6/6 块）；启发式仅剩"无 provenance 旧数据"兜底
  - DoD: 单测 +3（已知 id 跳过匹配 / provenance 直取 / 回写存储 provenance）✓；131 服务端测试全过 ✓；迁移已应用 + 回填 6/6 ✓
- [x] **T074 大文件上传决策登记（R33，2026-10-03 三期 P1）**：维持 200MB 整传（单用户/可靠链路/低频，业界阈值 >200MB 或不可靠链路才必须 tus）；触发条件入 R33——部署阶段（WAN）大文件上传成常态时接入 tus（tuspyserver）；无代码改动
- [x] **T075 跨语言检索调优：原问题常驻召回通道（R34，2026-10-03 用户选定专项）**：`_execute_plan` 多查询合并循环前插**原问题通道**（MultiQuery 惯例：原问题永远保留、改写是增量；时间范围沿用规划器首个时间窗；合并仍取 max）；诊断证据入 R34（g05 改写词袋 0.32 vs 原句 0.775；g06 重排短语抽奖 0.06↔0.92）；规划器"紧凑短语"提示词改动实测无增益已回退
  - DoD: 120 非验收测试全过（更新 1 例断言：原问题通道同样触发扇出）✓；生产路径探针：g05 锁稳（3/3、6/6）、g06 通过轮 0.64–0.92 ✓；全量测试 131 通过 ✓；服务重启后验收段复跑（含 SC-002 端到端）11 通过 / 1 跳过 ✓
  - 遗留立项（R34③④⑤）：替代重排器对比评测（重排短语脆弱性）；扇出假强命中专项（b02 类 0.712）；验收残留回写污染清理（b04 类）

## 遗留立项（跨语言专项 R34 排期，2026-10-03）

- [x] **T076 替代重排器对比评测（R34③）**：新建 `tests/acceptance/rerank_eval.py`——同一生产候选池（capture 补丁取出）复评隔离重排器变量 + 近义改写稳定性（4 题 × 5–8 改写）+ 延迟统计，报告落盘。实测：bge 分离 −0.298、抽奖跨度 0.90；**Qwen3-4B 分离 +0.643、跨度 ≤0.21、延迟 0.90s**；8B +0.812 但 1.46s/2×价；0.6B 判别力不足淘汰。**决策（用户选定）：切换 Qwen3-Reranker-4B**（`config.rerank_model`；阈值 0.60/0.50 沿用——正确分下限 0.79+/兜底上限 0.35，无需复标定）
  - Deps: 无
  - DoD: 评测报告 `rerank_eval_report.json`（4 候选 × 20 题 + 27 改写样本）✓；决策记录 R35 ✓；120 非验收测试全过 ✓；服务重启后验收段 11 通过/1 跳过、**SC-002 hit_rate 1.0（g06 修复）**✓
- [ ] **T077 扇出假强命中专项（R34④）**：量化 `_expanded_search`（R19 扇出）的收益与假强命中代价——兜底集（b01–b05）有/无扇出对照 + 命中集不得降召回；候选缓解（评测后择一）：扇出强命中须带实体/关键词佐证 / 扇出命中分数单独校准 / 收缩触发条件
  - Deps: T076（重排器若切换，本项测量需在其后）
  - DoD: 对照评测报告 + 选定缓解落地 + 回归（命中集不降、兜底假强命中消除）

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [Story] 标签映射 spec 的 user story（US1~US4），可独立验收
- 每个任务完成后勾选 `- [x]` 并对照 DoD 验证（/speckit-implement 依据）
- 避免：含糊任务、同文件冲突、跨 story 破坏独立性的依赖
