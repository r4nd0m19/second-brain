# Tasks: F2 Windows 浏览器采集（browser-capture）

**Input**: Design documents from `/specs/002-browser-capture/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/capture-api.md ✅, quickstart.md ✅

**Tests**: 依 plan.md 测试策略包含（pytest 单测/契约 + HTTP acceptance + 扩展 jsdom 单测）。

**Organization**: 按用户故事分组（US1 P1 / US2 P2 / US3 P3）。快照引擎已定稿 single-file-core（2026-10-02：验证冲刺取消，直接完整实现）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1/US2/US3）
- 每个任务携带两行缩进子项：
  - `Deps:` 依赖的任务 ID；无依赖写 `Deps: 无`
  - `DoD:` 完成标准（可验证，是 /speckit-implement 的验收依据）

## Path Conventions

- 服务端：`server/app/`、`server/tests/`；前端：`web/`；扩展：`extension/`（独立组件，见 plan.md 结构）

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 [P] 初始化扩展工程 extension/：package.json（deps: single-file-core@^1.6.20、@mozilla/readability@^0.6.0、defuddle；devDeps: esbuild、typescript、vitest、jsdom）、tsconfig.json、build.mjs（esbuild 打包 background/content/offscreen/options/popup → extension/dist）、目录骨架 src/{background,content,offscreen,shared,popup,options} 与 tests/
  - Deps: 无
  - DoD: `npm ci && npm run build` 产出 extension/dist；`npm test` 可运行（空用例）
- [X] T002 [P] 服务端配置扩展 server/app/config.py：`capture_max_snapshot_mb=20`、`capture_max_request_mb=100`、`capture_rate_limit=120`（每分钟 / 凭据）
  - Deps: 无
  - DoD: settings 加载通过；默认值与 plan 决策一致（20MB / 100MB）

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: 本阶段完成前不得开始任何用户故事。

- [X] T003 Alembic 迁移 server/alembic/versions/xxxx_add_browser_capture.py：documents 新增列（source_url text、site_name text、first_captured_at/last_captured_at timestamptz、visit_count int、snapshot_path text、snapshot_bytes bigint、snapshot_state text、capture_id uuid，全部 NULLABLE）+ partial UNIQUE `(owner_user_id, source_url) WHERE source_type='browser'` + B-tree `(source_type, last_captured_at)` + capture_tokens 表（id/owner_user_id/name/prefix/token_hash/scope NOT NULL DEFAULT 'capture'/created_at/last_used_at/revoked_at）+ SourceType CHECK 重建纳入 `browser`
  - Deps: 无
  - DoD: `alembic upgrade head` 与 `downgrade` 往返成功；结构逐项对照 data-model.md；既有 upload/conversation 行不受影响
- [X] T004 [P] 实体模型 server/app/models/entities.py：`SourceType.browser`；Document 新列（snapshot_state ∈ `kept`/`skipped_oversize`/`skipped_error`）；CaptureToken 模型
  - Deps: T003
  - DoD: 应用启动无错；test_db_smoke 扩展冒烟通过
- [X] T005 [P] 凭据工具 server/app/capture/security.py：生成 `sb_cap_`+32B 随机（base64url）、存 sha256、prefix=前 8 字符；校验（hash 匹配 + `revoked_at IS NULL` + scope）
  - Deps: T004
  - DoD: 单测：生成 / 校验 / 吊销后拒绝 / prefix 正确
- [X] T006 [P] token 认证依赖 server/app/capture/deps.py：Bearer 解析 → 校验 → 无效/吊销 401、scope 不符 403；`last_used_at` 节流更新（≥60s 才写）
  - Deps: T005
  - DoD: 单测覆盖 401/403/通过三路径
- [X] T007 [P] 网页正文入库 server/app/ingestion/webpage.py：Markdown 标题分块器（按 # 层级构建 heading_path；单块长度上限对齐既有 chunk 配置）；读 content.md → chunks（page=NULL）
  - Deps: 无
  - DoD: server/tests/test_webpage_chunker.py 通过（标题路径 / 长段落拆分 / 空文档）
- [X] T008 pipeline 分支 server/app/ingestion/pipeline.py：source_type=browser 走网页路径（免 Docling）；`processing → indexed`；进度文案沿用"索引中 x/y 块"格式
  - Deps: T007, T004
  - DoD: 集成：入库一条 browser 文档 → indexed 且 chunks 生成；上传类路径行为不回归

**Checkpoint**: 迁移 + 认证 + 入库路径就绪，可开始用户故事。

---

## Phase 3: User Story 1 - 浏览即自动入库，日后随问随答 (Priority: P1) 🎯 MVP

**Goal**: 扩展自动采集阅读过的网页（正文 + 快照）→ 入库 → 对话可问出细节并附出处（标题/链接/浏览时间）。
**Independent Test**: 真实浏览一篇文章 → 对话问其中细节 → 回答正确、出处指向该网页（quickstart §1–3）。

### Tests（先行，预期失败）

- [X] T009 [P] [US1] 契约测试先行 server/tests/test_capture_ingest.py：401/403、URL 规范化（去 fragment 留 query）、201 新建 / 200 幂等(capture_id) / 200 更新(同 URL, reindexed)、超限→`skipped_oversize`、413、429
  - Deps: T008
  - DoD: 用例覆盖 contracts/capture-api.md 全部分支（当前失败）
- [X] T010 [P] [US1] 扩展单测先行 extension/tests/trigger.test.ts + url.test.ts：可见停留累计（隐藏不计）、滚动深度、阈值组合（≥10s 或 ≥50%，可配置）、SPA 重置；URL 规范化与服务器一致
  - Deps: T001
  - DoD: 用例可运行（当前失败）

### Implementation — Server

- [X] T011 [US1] 快照存储 server/app/storage/local.py：`{owner}/{doc}/snapshot.html.gz`；gz 原样保存 / 非 gz 落盘时压缩；记 sha256 + bytes；覆盖更新替换旧文件
  - Deps: T003
  - DoD: test_storage 扩展通过（路径安全 / 覆盖 / 删除目录时快照同清）
- [X] T012 [US1] 采集接收 POST /api/capture/pages server/app/capture/router.py：multipart（url 必填；file/text 二选一；title/captured_at/capture_id 可选）；URL 规范化；三分支（新→201 / capture_id 幂等→200 / 同 URL 更新→200 reindexed 判定）；超限降级；enqueue_ingestion
  - Deps: T006, T008, T011
  - DoD: T009 中 201/200 幂等/更新/降级/401/403 分支转绿（413/429 断言由 T014 完成后转绿）；与 SingleFile 官方扩展 REST 格式（url+file 字段）可直传
- [X] T013 [US1] 连接探测 GET /api/capture/ping
  - Deps: T006
  - DoD: 200 `{ok,owner,scope,server_version}`；401/403 区分
- [X] T014 [US1] 限速 + 请求体天花板：按 token 滑窗限速（429 + Retry-After）；multipart 总大小 >100MB → 413（流式校验）
  - Deps: T012
  - DoD: 单测：超限触发 429 / 413；无整包读入内存；T009 全部断言至此转绿
- [X] T015 [US1] 凭据管理端点 server/app/capture/tokens_router.py（会话认证）：GET 列表 / POST 创建（明文仅此一次）/ DELETE 吊销（置 revoked_at 保留行）
  - Deps: T005
  - DoD: 单测：创建返回 `sb_cap_` token；吊销后 ping 立即 401
- [X] T016 [US1] 回放端点 server/app/documents/router.py：GET /api/documents/{id}/snapshot（会话）：CSP sandbox 全串 + nosniff + `Content-Encoding: gzip` 直出；无快照 404 / 文件缺失 410
  - Deps: T011
  - DoD: 响应头逐项对照 contracts；单测通过
- [X] T017 [US1] 出处字段扩展 server/app/retrieval/search.py + server/app/chat/orchestrator.py：RetrievedChunk 增 source_url/last_captured_at（join 带出）；to_citation 对 browser 附两字段；_format_hit 网页来源标注
  - Deps: T004
  - DoD: 单测：browser 命中 citation 含新字段；上传来源不回归

### Implementation — Extension

- [X] T018 [P] [US1] shared/trigger.ts + shared/url.ts：纯逻辑实现（可见停留 / 滚动深度 / 阈值 / SPA 重置；URL 规范化）
  - Deps: T010
  - DoD: T010 转绿
- [X] T019 [US1] 内容脚本 extension/src/content/index.ts：Page Visibility 累计 + 底部哨兵 IntersectionObserver；达标 → 提取 → 消息 SW（消息重试）；SPA 路由重置（webNavigation.onHistoryStateUpdated，SW 侧转发）
  - Deps: T018
  - DoD: 手测：达标产生提取与消息；未达标无动作；SPA 切路由清零
- [X] T020 [P] [US1] 正文提取 extension/src/content/extract.ts：Readability（document.cloneNode(true)、isProbablyReaderable 预检）+ defuddle 兜底 + MutationObserver 静默窗口（1–2s）重试、上限后降级仅元信息
  - Deps: T001
  - DoD: 三类页面（静态文章 / SPA / 短页）手测产出 title+text；失败路径返回空且不抛
- [X] T021 [P] [US1] 快照模块 extension/src/shared/snapshot.ts：`captureSnapshot(): Promise<Blob>` 单一接口封装 single-file-core（blockScripts/removeHiddenElements/removeUnusedStyles/compressHTML/groupDuplicateImages 默认开启，实现时核对选项名）；>20MB 本地预判降级不传快照
  - Deps: T001
  - DoD: 常见页面返回单文件 HTML Blob；调用方不感知内核（接口隔离）
- [X] T022 [P] [US1] SW 队列 extension/src/background/queue.ts：**先原子写 storage.local**（id/url/title/text/captured_at/status/attempts/nextRetryAt）；快照 Blob 入 IndexedDB；监听器顶层注册
  - Deps: T001
  - DoD: 手测：写入后 SW 被杀再启动，队列可恢复
- [X] T023 [US1] 上传 extension/src/background/upload.ts + src/offscreen/（html+ts）：`CompressionStream('gzip')`；fetch 短超时（<30s）；capture_id 幂等；`chrome.alarms` 退避 1/2/4/8/16→60min、max5 → dead-letter + badge；SW 启动重建 alarm；大 Blob 走 offscreen document
  - Deps: T022, T013
  - DoD: 手测：停服积压 badge 变黄；恢复后自动补传且服务端无重复条目
- [X] T024 [US1] manifest + options extension/manifest.json + src/options/：permissions {storage, alarms, offscreen, webNavigation, unlimitedStorage}；content_scripts `<all_urls>`；optional_host_permissions（`https://*/*` + loopback）；`incognito: not_allowed`；options：URL 校验（仅 https/loopback）、token（password 型）、保存并测试（/health→ping）、用户手势内 `chrome.permissions.request`、`storage.local` + `setAccessLevel('TRUSTED_CONTEXTS')`、onInstalled 自动打开
  - Deps: T013, T001
  - DoD: sideload 无警告；三态展示（不可达 / 未授权 / 已连接）
- [X] T025 [US1] popup extension/src/popup/：连接状态 / 队列深度 / 最近错误 / 今日计数
  - Deps: T022
  - DoD: badge 三态与 popup 数据准确（对照队列手测）

### Implementation — Web

- [X] T026 [US1] 凭据管理 UI web/lib/api.ts + web/app/page.tsx：列表（prefix/last_used/revoked）、新建 show-once 弹层（复制）、吊销确认
  - Deps: T015
  - DoD: 新建→复制→吊销全流程可用
- [X] T027 [US1] 对话出处渲染 web/app/chat/page.tsx：browser citation 卡片（标题 / 站点 / 浏览时间 + 打开原文 + 查看快照）
  - Deps: T017
  - DoD: browser 命中渲染正确；上传来源卡片不回归
- [X] T028 [US1] 快照回放页 web/app/snap/page.tsx：`<iframe sandbox="">` 加载回放端点；页头标题 / URL / 时间 / 打开原文
  - Deps: T016
  - DoD: 手测渲染原貌；DevTools 无脚本执行

### Acceptance — US1

- [X] T029 [P] [US1] acceptance server/tests/acceptance/test_capture_scenarios.py：SC-001（HTTP 模拟采集→indexed→问答→出处含 url/时间）、SC-008 原型（回放 200 + CSP/nosniff/gzip 头断言）
  - Deps: T012, T016, T017
  - DoD: 新用例通过（自清理）

**Checkpoint**: US1 独立可验（quickstart §1–3 + §6）——MVP 达成。

---

## Phase 4: User Story 2 - 采集的可见、可控与隐私边界 (Priority: P2)

**Goal**: 看见采集了什么、单条删、黑名单源头不采、一键暂停。
**Independent Test**: 黑名单域名零数据（含元信息）；删除后检索/出处同步消失（quickstart §3）。

- [X] T030 [P] [US2] 单测先行 extension/tests/block.test.ts：黑名单匹配（精确域 + 子域语义）、暂停判定
  - Deps: T018
  - DoD: 用例可运行（当前失败）
- [X] T031 [US2] 黑名单 + 暂停：extension/src/shared/block.ts + 内容脚本测量前判断（含元信息不采）+ SW 二次闸门 + options 管理 UI（域名增删）
  - Deps: T030, T019
  - DoD: 黑名单域名浏览 → 无任何网络请求、队列无条目（单测 + 手测）
- [X] T032 [US2] 计数与快捷开关：今日计数（本地日期）+ 暂停开关（popup）
  - Deps: T031
  - DoD: 计数随采集 +1；暂停后无新条目、恢复后继续
- [X] T033 [US2] 列表端点与筛选：GET /api/documents?source=browser（字段同 contracts）+ web/app/page.tsx 来源筛选与字段展示（标题 / 站点 / 时间 / 次数 / 快照状态）
  - Deps: T004
  - DoD: 筛选与展示手测正确；F1 上传列表不回归
- [X] T034 [US2] 批量清理端点 DELETE /api/documents?source=browser&before&after（必须显式 source=browser；至少一时间界）→ 200 `{deleted}`
  - Deps: T003
  - DoD: 单测：行 + 快照文件 + chunks 全清；缺参 400
- [X] T035 [US2] 清理 UI web/app/page.tsx：时间范围选择 + 二次确认 + 结果计数
  - Deps: T034
  - DoD: 手测：删除后列表 / 检索 / 出处同步消失、快照 404
- [X] T036 [P] [US2] acceptance：SC-003（断言服务端无黑名单域名任何行——配合扩展手测记录）、SC-004（删除后问答不再引用 + snapshot 404）
  - Deps: T031, T034
  - DoD: 新用例通过

**Checkpoint**: US1 + US2 共同可验（quickstart §3）。

---

## Phase 5: User Story 3 - 时间维度回找 (Priority: P3)

**Goal**: "我上周看过哪些网页"（清单）与"上周看过的 X"（语义×时间组合）。
**Independent Test**: seed 跨时间窗数据 → 两类时间问题返回正确（quickstart §5）。

- [X] T037 [P] [US3] 单测先行 server/tests/test_timerange.py：今天/昨天/前天/本周/上周/最近 N 天/N 天前（中文数字）/上个月/今年；半开区间；周一为周首；跨年 / 跨月；锚点=消息时刻
  - Deps: T003
  - DoD: 用例可运行（当前失败）
- [X] T038 [US3] 规则解析器 server/app/chat/timerange.py：输出 `{start,end,granularity,confidence,intent}`（intent ∈ list/search/none；Asia/Shanghai）
  - Deps: T037
  - DoD: T037 转绿
- [X] T039 [US3] LLM 兜底 + 校验：规则未命中 / 模糊时调既有模型（严格 JSON）；`start ≤ end`、跨度 ≤5 年（可配置）；低置信 / 未来时间不静默使用（回退无过滤）；失败降级
  - Deps: T038
  - DoD: 单测：模糊表达走兜底；非法输出被拒并回退
- [X] T040 [US3] 检索时间过滤 server/app/retrieval/search.py：可选 `[start,end)` 参数；向量分支 `SET LOCAL hnsw.iterative_scan=relaxed_order` + `ef_search=100`；关键词分支同滤；EXPLAIN ANALYZE 验证索引路径
  - Deps: T004
  - DoD: 单测：命中均在窗口内；EXPLAIN 结果记录
- [X] T041 [US3] orchestrator 接入 server/app/chat/orchestrator.py：解析 → `list` 直出清单（SQL 按 `last_captured_at` desc，回答回显时间范围）| `search` 带过滤检索 | `none` 行为不变
  - Deps: T038, T039, T040
  - DoD: 三类问题手测/单测正确；无时间表达问题与 F1 行为一致（回归）
- [X] T042 [P] [US3] acceptance：SC-007（seed 跨窗文档 → 清单问题核对 + 组合检索命中且回显范围）
  - Deps: T041
  - DoD: 新用例通过（自清理）

**Checkpoint**: 三个故事全部独立可验。

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T043 [P] 安全复核：回放页 XSS 试探（含 script 快照不执行）、吊销即时生效、无 Origin 白名单断言、无痕不注入（incognito 设置）、host 权限提示复核
  - Deps: T016, T024
  - DoD: 逐项记录（quickstart 验收记录）；发现问题即修
- [X] T044 [P] 检索性能回归：时间过滤混合检索在 10 万 chunk 规模不显著降级（复用 tests/perf 基线方法）
  - Deps: T040
  - DoD: 数据记录并与 F1 基线对比
- [ ] T045 quickstart 全量验收：安装 → 采集 → 隐私（含备份链路：快照入 storage-mirror、删除后同步消失）→ 离线 → 时间 → 快照 → 回归（含真机手动项：Windows sideload、真实浏览无感、断网补传）；SC-002（≥10 题、≥3 天前浏览样例 ≥80%）执行
  - Deps: T029, T036, T042
  - DoD: quickstart 清单勾选完成（含备份项：backup.sh 后 storage-mirror 含 snapshot.html.gz，删除条目后再跑同步消失）；SC-002 结果记录；失败项开修复任务
  - 进展（2026-10-02 真机实测，Windows Chrome）：sideload 安装/重装 ✓；真实浏览自动采集 ✓（含 SPA、重页面）；快照生成/上传/回放 ✓（最大 17MB）；完成反馈（右下角提示+标签页徽标）✓；离线队列重试/退避/幂等 ✓；时间类问句（"最近3天看过哪些"）✓；Markdown 回答渲染 ✓；备份链路 ✓（演练通过，含使用中写入竞态重试）。**待办**：黑名单源头拦截真机复核、断网 30 分钟补传（SC-005 真机）、SC-002 浏览语料样例题集
- [X] T046 文档收尾同步：001-core-qa/contracts/api.md（documents 端点变更）、001 tasks.md 关联、project.md 检查（无则说明）；本 tasks.md 勾选更新
  - Deps: T045
  - DoD: 收尾报告列出同步清单；pre-commit 提醒无残留

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 立即开始；T001/T002 并行
- **Foundational (Phase 2)**: 依赖 Setup；**阻塞全部用户故事**（T007 可提前并行）
- **User Stories (Phase 3+)**: 依赖 Foundational
- **Polish (Phase 6)**: 依赖所需故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 后即可；无故事间依赖（MVP）
- **US2 (P2)**: 依赖 US1 的扩展基座（T019/T022）与列表基础（T033 仅依赖 T004）
- **US3 (P3)**: T040 仅依赖 T004（可与 US1 并行）；T041 集成依赖 US1 数据流入

### Within Each Story

- 测试先行（T009/T010/T030/T037 先红）→ 模型/工具 → 端点/服务 → UI → acceptance
- 服务端与扩展任务在各自 story 内并行推进（文件不重叠）

### Parallel Opportunities

- Setup：T001 ∥ T002
- Foundational：T004 ∥ T007（其余按 Deps 链）
- US1：T009 ∥ T010；T011/T015/T017 可并行；T018/T020/T021/T022 可并行；T026/T027/T028 可并行
- US2：T030/T033/T034 可并行起步
- US3：T037 ∥ T040
- Polish：T043 ∥ T044

---

## Parallel Example: User Story 1

```bash
# 测试先行（两个测试文件）:
Task: "契约测试 server/tests/test_capture_ingest.py（T009）"
Task: "扩展单测 extension/tests/trigger.test.ts + url.test.ts（T010）"

# 扩展核心模块（互不依赖）:
Task: "shared/trigger.ts + shared/url.ts（T018）"
Task: "content/extract.ts（T020）"
Task: "shared/snapshot.ts（T021）"
Task: "background/queue.ts（T022）"
```

---

## Implementation Strategy

### MVP First（US1）

1. Setup + Foundational → 基座就绪
2. US1 全部任务 → **STOP & VALIDATE**：quickstart §1–3 + §6（真实浏览 → 问答 → 出处 → 快照回放）
3. 通过即 MVP 达成（日常浏览采集可用）

### Incremental Delivery

1. US1 → 验收 → 可用
2. +US2（可见可控）→ 验收（黑名单 / 删除 / 暂停）
3. +US3（时间回找）→ 验收
4. Polish（安全复核 / 性能 / 全量 quickstart / 文档同步）→ 收尾

### Notes

- 每任务含 Deps/DoD；DoD 为验收依据
- 每完成一个任务或逻辑组即提交；完成一个故事跑一次 acceptance
- 扩展相关任务在 Windows 真机验证（sideload）；服务端任务本地即验
- 避免：跨故事拆同一文件（entities.py / page.tsx 的多次修改按任务顺序串行）

## 2026-10-02 试用增强补记（as-built，用户驱动）

- [x] **T046 反爬验证页过滤 + 重复采集窗口**：扩展侧 `shared/skip.ts`（DDoS-Guard/Cloudflare 等特征 + FNV-1a 内容指纹 10 分钟窗口）接入 content 采集判定；清理被自动刷新循环重复采集 109 次的垃圾记录；验收测试凭据自动收尾（吊销→删除）
  - DoD: 单测 +11（36 通过）；Windows 装载目录同步；spec Edge Cases/FR-005 已更新 ✓
- [x] **T047 凭据彻底删除 + 凭据区精简（FR-015）**：`DELETE /api/capture/tokens/{id}?purge=1`（仅限已吊销，未吊销 409）+ UI 折叠/已吊销默认隐藏/已吊销行「删除」按钮 + 验收 helper 自动清理
  - DoD: 单测（409 / 删除后列表消失 / 再删 404）；真机流程（创建→409→吊销→204）；契约已更新 ✓
- [x] **T048 浏览记录列表卡片化 + 分页/搜索/排序**：与 001 共享端点与组件；`source=browser` 默认排序 = 最近浏览↓；卡片行布局去横向滚动
  - DoD: 见 001-core-qa/tasks.md T046 证据（同一批测试）✓
- [x] **T049 浏览清单截断透明化 + 验收稳健性（2026-10-02）**：`_list_reply` 展示上限 50 条、超限时注入"仅为最近 50 条"口径防失实（原"完整记录"表述在窗口 >50 条时错误——真实数据 55 条时被发现）；sc007 用例"近三天"条目改用当前时间（防被窗口内 >50 条截断而不可见）
  - DoD: 单测 `test_chat_list_reply.py`（51 条截断/50 条完整各一例）；验收 sc007 恢复绿 ✓；spec FR-012 已增补 ✓
- [x] **T050 浏览清单意图覆盖 + 防编造（2026-10-03 实测）**：「浏览了什么内容」类问句补入清单意图词表（此前误判语义路径 → "没有资料"）；提示词禁止无资料时编造浏览条目；守卫补「没有收到/没有查到」变体（详见 001 research R20）
  - DoD: 单测 +6；真机「我昨天浏览了什么内容」→ 清单直达 50 条真实记录、范围准确、不编造 ✓
  - 后续：该词表机制已由 001 FR-022 查询规划器整体取代（2026-10-03，R21）——保留为历史记录；浏览清单能力以 `list_browsing` 工具延续（含站点聚合）
- [x] **T051 sc007 断言改引用确定性 + 组合问句修正（2026-10-03）**：追查验收抖动——原断言"条目标题逐字出现在回答中"在回答为聚合摘要时约 1/4 概率失败（非检索故障：清单材料 50 条时模型按站点归类概述、不逐条列名）；改为验证 citations（近三天条目在、窗口外条目不在）——材料来自数据库查询、为确定性事实。联动修复：001 规划器补"内容/清单边界"与"历史不越权"判据（R21 续三·追记）——组合问句「最近3天看过的网页里 X 是什么」此前约 1/4 概率被规划为 list_browsing（材料仅元数据、无正文可用）
  - DoD: sc007 循环 10/10 ✓；全量验收 11 通过 / 1 跳过 ✓
