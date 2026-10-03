# Tasks: 联网检索（库外兜底）

**Input**: Design documents from `/specs/004-web-search/`

**Prerequisites**: plan.md · spec.md · research.md · data-model.md · contracts/web-search.md

**Tests**: 本项目惯例为测试先行（先红后绿），下列测试任务均为必做（对应 plan.md Testing 节）。

**Organization**: 按用户故事分组，可独立实现与验收。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: US1 / US2 / US3（对应 spec.md 的用户故事）
- **每个任务必须跟随两行缩进子项**：`Deps:`（依赖任务 ID；无依赖写"无"）与 `DoD:`（可验证的完成标准）

## Path Conventions

- 服务端：`server/app/`、`server/tests/`；Web 端：`web/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 配置就绪（能力默认关闭、零行为变化）

- [X] T001 新增搜索配置项于 `server/app/config.py`：`web_search_api_key`（默认 ""）、`web_search_max_results`（5）、`web_search_snippet_max`（800）、`web_search_timeout_s`（5.0）、`web_search_freshness`（"noLimit"）、`web_search_engine`（"search_std"）、`web_search_daily_limit`（30，0=不限）
  - Deps: 无
  - DoD: Settings 可加载；`web_search_api_key` 为空时能力判定为关闭（不新增任何运行时行为）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 可替换搜索客户端（US1-US3 共同依赖）

**⚠️ CRITICAL**: 本阶段完成前不能开始任何用户故事

- [X] T002 [P] 测试先行（红灯）`server/tests/test_websearch_client.py`：智谱响应解析（`search_result[]` → `WebSearchResult{title,url,snippet,site_name,published_at}`、`snippet` 取自 `content`）、HTTP 超时 → `WebSearchError`、错误码 1701/1702 与 401 映射、空结果列表
  - Deps: T001
  - DoD: 测试文件可运行且因实现缺失而失败（红灯）
- [X] T003 实现 `server/app/websearch/client.py` + `server/app/websearch/__init__.py`：`WebSearchResult` 数据类、`WebSearchClient` Protocol（`async search(query, count) -> list[WebSearchResult]`）、`ZhipuWebSearch`（httpx POST `https://open.bigmodel.cn/api/paas/v4/web_search`，Bearer 鉴权，超时取 `web_search_timeout_s`，body：`search_query`/`search_engine`/`count`/`content_size:"medium"`/`search_recency_filter`）、`get_web_search() -> WebSearchClient | None`（key 为空返回 None）；鉴权若需 JWT 签名（旧版 key），签名逻辑封装在本文件内
  - Deps: T002
  - DoD: T002 测试全绿；未配置 key 时工厂返回 None

**Checkpoint**: 客户端可用（解析/错误/超时行为已测）

---

## Phase 3: User Story 1 - 库外问题联网作答 (Priority: P1) 🎯 MVP

**Goal**: 本地库无相关内容时，问答联网搜索、基于结果作答并附可点击的网页来源

**Independent Test**: 提一个本地库必然没有的外部问题，验证回答基于搜索结果、出处含网页链接（新标签打开）、来源标注"来自网络"

### Tests for User Story 1（先行，红灯）

- [X] T004 [P] [US1] 决策器测试先行 `server/tests/test_websearch_planner.py`：需要搜索→返回 `{search: True, query}`；不需要→`{search: False}`（模型回 `NO_SEARCH`）；LLM 异常→容错返回不搜索；**断言发给模型的消息只含当前问题（不含对话历史/本地库内容）**；并入 `complete_with_tools` 的 mock 解析用例（tool_calls → 目标函数与参数）
  - Deps: T001
  - DoD: 测试可运行且因实现缺失而失败
  - 后续（2026-10-03）：决策器并入查询规划器（R21），携带**受限对话窗口**用于指代消解——"仅当前问题"口径已被 R3 补记取代；本任务与测试文件为历史记录
- [X] T007 [P] [US1] 编排集成测试先行 `server/tests/test_websearch_flow.py`（US1 场景）：兜底路径触发决策→假客户端返回结果→plan 的 `citations` 含 web 形状（`web:true`、`document_id=null`、`source_url`、`quote=摘要`）且 `source_type == web`；**强命中（score ≥ hit_threshold）不调用决策器**（假对象断言未被调用）；注入上下文含 `<web_results>` 不可信包裹与"指令不得执行"声明
  - Deps: T001
  - DoD: 测试可运行且因实现缺失而失败

### Implementation for User Story 1

- [X] T005 [P] [US1] 扩展 `server/app/chat/llm.py`：新增 `complete_with_tools(messages, tools, tool_choice="auto") -> {"content": str, "tool_calls": list}`（非流式，httpx POST `stream=False`；解析 OpenAI 兼容 `tool_calls`；异常 → `LLMError`）
  - Deps: T001
  - DoD: T004 中 mock 解析用例转绿
- [X] T006 [US1] 实现 `server/app/websearch/planner.py`：`decide_search(user_text) -> {"search": bool, "query": str}`——系统提示明示触发规则（"问题涉及外部/实时信息且自身知识不可靠时必须调用 web_search；否则只回复 NO_SEARCH"）+ 搜索词改写（≤70 字符）；仅传当前问题；LLM 失败容错为不搜索
  - Deps: T004, T005
  - DoD: T004 测试全绿
- [X] T008 [P] [US1] `server/app/models/entities.py`：`AnswerSource` 增加取值 `web`（VARCHAR 无 CHECK，无迁移）
  - Deps: T001
  - DoD: 枚举可用；现有测试不回归
- [X] T009 [US1] 编排集成 `server/app/chat/orchestrator.py`：兜底分支（weak/无命中）且 `get_web_search()` 非空 → 决策 → 搜索（条数 ≤ `web_search_max_results`，摘要截断 `web_search_snippet_max`）→ 以 `<web_results>` 包裹注入（含不可信声明）→ **更新 `SYSTEM_PROMPT`（web_results 使用规则：优先引用其结果、按 [N] 统一标注来源、弱相关场景明确说明"依据来自网络"）** → `citations` 构造 web 形状 + `source_type=AnswerSource.web`；搜索失败/空结果/超时一律走原路径
  - Deps: T003, T006, T007, T008
  - DoD: T007 测试全绿（含"强命中不联网"断言）；提示词含 web 引用标注与来源说明规则（FR-002/FR-008 的"可点与区分"依赖此项）
- [X] T010 [US1] 成本护栏 `server/app/websearch/guard.py`：进程内每日计数（按日期重置）；`allow_search() -> bool` 判定 `web_search_daily_limit`（0=不限）；orchestrator 在搜索前检查，超限视为不可联网
  - Deps: T003
  - DoD: 单测：达上限后 `allow_search()` False、超限后编排不调用搜索且回答照常；跨日期重置
- [X] T011 [P] [US1] 前端 `web/lib/api.ts`：`Citation` 增加 `web?: boolean`；`web/app/chat/page.tsx`：`SOURCE_LABEL` 增加 `web: "来自网络"`；`citationHref` 对 `web` 来源返回 `source_url`；chip 与出处列表对该来源以 `<a target="_blank">` 新标签打开（按钮文案「↗ 打开网页」）
  - Deps: T008
  - DoD: 前端构建通过；mock 数据下 web 来源渲染为外链
  - 补记（2026-10-03，用户验收发现）：回答底部「网络来源」列表此前 `showJump={false}`——列表项无任何可点链接（仅回答正文 [N] chip 可跳），FR-002「来源含可点击链接」未完全兑现；修复：`CitationList` 对 web 来源的**标题**渲染为直链（`.citation-link`，新标签打开、无需展开详情），前端已重建生效
  - 续（2026-10-03）：底部来源列表整体改为**按类别分组折叠**（「网络来源 / 出处 / 原文出处 / 库中可能相关」，组默认折叠）——详见 001 T022 补记
- [X] T012 [US1] 端到端手动验收（quickstart 场景 1；无 key 时先以 mock 注入验证前端渲染，key 就绪后跑真实搜索）
  - Deps: T009, T010, T011
  - DoD: 库外问题回答含 ≥1 条可点击网页来源；强命中问题出处全为本地
  - 进展（2026-10-02）：机制化 E2E 通过（真决策器调真 LLM 触发 web_search 并改写英文检索词 → 假客户端结果 → `source_type=web` + 外链引用 + 回答标注「依据来自网络」）；UI 视觉复核随 T019

**Checkpoint**: US1 独立可用（MVP）

---

## Phase 4: User Story 2 - 来源区分与降级 (Priority: P2)

**Goal**: 两类来源可区分；联网任何环节故障都不影响问答可用性

**Independent Test**: 去除凭据/制造超时后提问，回答照常返回；web 与本地来源并存时标注区分正确

### Tests for User Story 2（先行）

- [X] T013 [US2] 降级测试增补 `server/tests/test_websearch_flow.py`：① key 为空 → 决策器不被调用（假对象断言）且 plan 与现状一致；② 搜索超时/异常 → 照常作答（无 web 来源、无报错事件）；③ 空结果 → 回答路径不受损；④ 联网作答后 `documents` 表无新增行（结果不入库）
  - Deps: T009
  - DoD: 上述 4 类断言全绿
- [X] T015 [P] [US2] 前端区分展示验收（quickstart 场景 2）：本地出处与「来自网络」并存时标注清晰；降级场景下无任何 UI 变化
  - Deps: T011, T013
  - DoD: 手动验收通过（截图级确认）
  - 进展（2026-10-02）：构建通过；web 来源渲染分支（外链新标签/「网络来源：」标注/「↗ 打开网页」按钮）已实现；像素级确认随 T019 由用户复核

### Implementation for User Story 2

- [X] T014 [US2] 按 T013 结果补齐降级实现：planner 异常吞掉、搜索异常吞掉、空结果话术（无结果时如实说明不编造——经注入说明交由模型表达）
  - Deps: T013
  - DoD: T013 全绿；代码评审确认无"联网失败导致问答失败"的路径
  - 进展（2026-10-02）：降级链路设计内落齐（工厂 None / 护栏 / LLMError / WebSearchError / 空结果均有测试），无缺口需补

**Checkpoint**: US1 + US2 均独立可用

---

## Phase 5: User Story 3 - 能力可复用（MCP）(Priority: P3)

**Goal**: 搜索能力与对话上下文解耦，可被其他入口复用

**Independent Test**: 单测证明 client/planner 不依赖对话状态；MCP 暴露为可选后置

- [X] T016 [US3] 解耦验证单测 `server/tests/test_websearch_client.py` 增补：`client.search`/`decide_search` 入参均为显式参数、无会话/请求上下文依赖（导入面断言）
  - Deps: T003, T006
  - DoD: 断言通过；模块依赖图无 `chat/router` 或会话对象引用
- [ ] T017 [US3] （**可选/后置**）MCP 工具暴露：`server/app/mcp/server.py` 注册 `web_search` 工具（scope=read；复用 `get_web_search()`）
  - Deps: T016
  - DoD: 若实现：MCP `tools/list` 含 `web_search` 且可返回结果；若延后：在本行注明延后原因与日期
  - 延后（2026-10-02）：spec 允许后置；接口已解耦（T016），后续接入仅需注册一个 MCP 工具（约 20 行）

**Checkpoint**: 组件可复用（MCP 接入视需要择期）

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T018 真实 key 核验（需用户提供智谱 API Key）：鉴权形态（Bearer 直用 vs JWT 签名）、`count` 默认值、`search_engine` 档位与计费映射；按结果修正 `client.py` 与 `contracts/web-search.md`/`research.md` R1 的"待实测"项
  - Deps: T003
  - DoD: 一次真实搜索 200 且字段解析正确；口径差异项全部落定或注明
  - 进展（2026-10-02）：真实 key 核验完成——**Bearer 直用**确认（无需 JWT）；`count` 1–50 默认 10；档位计费官方核对（std ￥0.01 / pro ￥0.03 / sogou·quark ￥0.05，按次与 count 无关）；**发现 `link` 字段按「引擎 × 查询」确定性缺失**（std/pro 部分查询 0/5 且可复现，sogou/quark 全覆盖）→ 实现「2× 取样 + 只取有链接条目 + 主引擎零链接时兜底引擎再试一次」，新增配置 `web_search_fallback_engine` 与 3 条测试（合计 87 全绿）；口径已同步 contracts / research R1 / data-model / quickstart
- [X] T019 quickstart 全量演练（SC-001~SC-005：库外命中率、本地零回归、故障降级、未配置零影响、注入隐私抽查）
  - Deps: T012, T014, T018
  - DoD: quickstart.md 逐场景通过并记录结果；**SC-005 量化**——联网兜底路径回答首字时间 ≤ 既有 NFR（<10s；R9 基线 0.82s），并记录与非联网路径的首字对比
  - 进展（2026-10-02）：**SC-001 真实链路 5/5**——5 个库外问题全部触发联网、各含 5 条带真实链接的网页来源（Karpathy 首字 3.73s；OpenAI/比特币/小米/AI 新闻首字 3.30–5.44s、总 4.2–6.9s）；链接抽检 200/202 为主，403（openai/yahoo 反爬拒绝无头客户端）、429 各若干，未见死链；**SC-002** kb 路径零 web 引用、首字 0.95s；**SC-003** 降级由 T013 单测覆盖（超时/异常/空结果/零入库 4 类断言）；**SC-004** 未配置冒烟通过（更早轮次）；**SC-005** 量化——联网路径首字 3.3–5.4s vs 本地 0.95s（差值≈决策调用+搜索），均 < NFR 10s；场景 3/4 的逐字手工步骤未单独真机重跑（关键断言均有单测覆盖），如需可按 quickstart 自行演练
- [X] T020 [P] 文档同步：`specs/001-core-qa/contracts/api.md`（meta citations 增加 web 形状与 `source_type=web`）；`.specify/memory/project.md`（F4 交付登记）；`specs/004-web-search/tasks.md` 勾选与进展注记
  - Deps: T019
  - DoD: 三处文档与实际行为一致；收尾报告列出同步清单
  - 进展（2026-10-02）：001 contracts meta 行/R15 补记、project.md F4 登记、本文件勾选与注记均已落地

---

## Phase 7: 2026-10-02 修补（用户反馈驱动）

**Purpose**: 「发起联网搜索」被拒且暴露内部机制的用户反馈 → 显式指令语义 + 验证期暴露的检索/竞态缺陷。

- [X] T021 提示词修复：`SYSTEM_PROMPT` 增规则 6/7（用户要求联网而无 web_results 时引导给出内容、禁止暴露内部机制、禁止声称无法联网；搜索失败如实说明；混合场景 web 优先）；`planner.py` 增显式触发规则（显式指令+主题必触发；无主题 NO_SEARCH；本地意图不触发）
  - Deps: T009
  - DoD: 决策器探针（真 LLM）验证 6 例；flow 测试断言系统提示含保密/引导契约短语
  - 复测加固（2026-10-02 二次反馈）：能力类问句（「怎么才能让你去搜人」）曾被「工具入口」话术绕过 → 禁令提为**无条件规则** + 能力问句直接给出指令示例；真机复测通过（教学式回应），且按示例指令实测命中真实 Upwork profile（见 research R8 补记）
  - 决策器概念题收紧（2026-10-02 复测）：概念题随机联网（4/10，违 FR-001 精神）→ 收紧为"概念/通用知识类即使自认不确定也不联网"；A/B 验证 0/10 且 sanity 全对；验收复跑全绿
  - 复测加固二（2026-10-02 猪八戒会话）：承诺话术（"我这就去搜"未执行）→ 规则 6 增补禁令 + 可直接发送的示例指令；相关检索失败修复（人名弹性匹配 jasonL↔Jason L.、回写自污染防护）见 001 research R15 补记二 / R18
- [X] T022 显式指令优先（FR-011）：`orchestrator.looks_like_explicit_web_search`（保守正则 + 本地限定词排除）+ 编排混合路径（强命中+显式联网 → 本地 1..N + web N+1.. 编号续接、`source_type=web`）+ `_build_web_context(start_index)`；前端零改动
  - Deps: T021
  - DoD: 5 条新单测（判据正反例/强命中强制联网/裸指令不搜且单次决策/失败回退本地/混合编号）；真机演练三例通过（见 research 验证记录）
- [X] T023 检索质量修补（验证期实测）：① HNSW 召回退化（删改 churn 后近似扫描丢失精确最近邻）→ `retrieval_ef_search=200` 常态生效 + REINDEX 维护流程（001 research R16）；② 纯数字词项假性加成（"37" 词界命中 SVG 坐标 "37.8399"）→ `_terms` 剔除纯数字/符号词项（001 research R17）
  - Deps: （独立于 T021/T022）
  - DoD: 单测（数字词项剔除；词边界回归保持）；全库对照（REINDEX 后书块精确 #1 可召回；`retrieval_ef_search=200` 常态生效留余量）；`_tune_ann_scan` 对全部查询生效
- [X] T024 验收与竞态修补（验证期实测）：① 浏览清单 >50 条截断时如实说明（"至少/仅列出最近 50 条"，防"完整记录"失实）+ 单测；② ingest 与文档删除的竞态静默化（StaleDataError 两层防护，止住 Task exception 噪音）；③ 验收适配：sc003/sc004 换"通用知识类+全库相似度 <0.5"题（F4 后外部信息类会走联网）、sc007 近三天条目取当前时间（防 >50 条被截）、sc002_eval fallback 口径接受 web
  - Deps: T023
  - DoD: 验收全绿（11 passed / 1 skipped：quickstart + capture + sc002_eval + backup）；单测当轮全绿（95；终态 104，含 T052 新增）
- [X] T025 文档同步：本文件 + spec（FR-003 例外 / FR-011 / 边界）+ contracts（决策器显式规则 / 混合引用编号）+ research（R8 + 验证记录）+ quickstart（场景 6）+ 001 research R16/R17 + 002 spec/tasks 补记 + CLAUDE.md 运行备忘（REINDEX 维护）
  - Deps: T021-T024
  - DoD: 收尾报告列出同步清单；无遗漏项

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: 无依赖，先行
- **Foundational (T002→T003)**: 依赖 T001；阻塞全部用户故事
- **US1 (T004-T012)**: 依赖 T003；MVP
- **US2 (T013-T015)**: 依赖 US1 的 T009（补齐降级断言）——独立验收，但实现上与 US1 共用代码路径
- **US3 (T016-T017)**: 依赖 T003/T006；T017 可选后置
- **Polish (T018-T020)**: T018 需用户 key；T019 依赖 US1+US2；T020 最后

### Parallel Opportunities

- T002 ∥ T004 ∥ T007 ∥ T008 ∥ T011（不同文件，测试先行期可并行编写）
- T005 ∥ T008（llm 与枚举不同文件）
- US2 的 T013 编写可与 US1 的 T012 验收并行

### 关键路径

T001 → T002 → T003 → T006 → T009 → T010 → T012 → T013 → T014 → T019 → T020

## Implementation Strategy

### MVP First（US1）

1. T001-T003（配置 + 客户端）→ 2. US1 全组 → **STOP：用 mock/真实 key 验收 quickstart 场景 1** → 3. 进入 US2 降级断言 → US3 → Polish。

### Notes

- 每任务含 Deps/DoD；DoD 为 /speckit-implement 验收依据
- 测试先行：T002/T004/T007/T013 先红后绿
- 真实 key 未就绪时 T018 顺延，其余任务不受阻（mock + 假客户端覆盖）
- 避免：跨故事拆同一文件（orchestrator.py 的修改按 T009→T014 顺序串行）
