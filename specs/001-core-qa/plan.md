# Implementation Plan: F1 核心问答（core-qa）

**Branch**: `001-core-qa` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-core-qa/spec.md`

## Summary

打通 F1 主干：**上传文件 → Docling 解析入库 → pgvector 混合检索问答（带出处）→ 外部模型兜底 → 回写闭环**，以可安装 PWA 形态在 Windows/Android 双端使用。技术路线：自研组件搭建；单体 FastAPI（Python）+ Next.js 静态导出前端（单进程托管）+ Postgres/pgvector + 云 embedding + 外部对话模型 API。

## Technical Context

**Language/Version**: Python 3.12+（后端）；TypeScript / Node 22（前端构建期）
**Primary Dependencies**:
- 后端: FastAPI、uvicorn、SQLAlchemy 2.x + asyncpg、pgvector-python、Docling（解析）、SSE 流式响应
- 前端: Next.js（`output: 'export'`）+ React；PWA（manifest + Service Worker）
**Storage**: PostgreSQL 16 + pgvector（HNSW 向量索引 + FTS 全文）；原始文件存磁盘（按归属目录，FR-013）
**Testing**: pytest（后端单元/集成）；SC-001~008 验收脚本（quickstart.md 场景化）
**Target Platform**: Linux 服务器（2C4G 起步）；客户端 = 浏览器 / 可安装 PWA（Windows、Android）
**Project Type**: web-service（单人自托管；架构面向多用户留路）
**Performance Goals**: 提问后 10 秒内开始流式回复；10 万内容块规模检索不显著降级
**Constraints**: 云 embedding 例外（见 Complexity Tracking）；对话模型仅收命中片段；数据全量自有服务器；备份为 v1 组成部分
**Scale/Scope**: 个人资料库（书籍/文档），10 万内容块级

## 设计决策与理由 (Design Decisions & Rationale) *(mandatory)*

### 技术栈选择
| 选择项 | 结论 | 理由 | 备选方案及放弃原因 |
|--------|------|------|--------------------|
| 总体路线 | 自研（组件搭建） | spec 定制行为多，代码可控；长期个人基础设施 | 二开 Khoj/AnythingLLM（定制冲突 + 许可/维护），详见 research.md R1 |
| 后端 | Python 3.12 + FastAPI | RAG 生态最强（Docling 仅 Python）；SSE 流式标准 | 纯 TS（解析弱）、Node 后端 |
| 前端 | Next.js 静态导出（PWA） | 前端体验 + FastAPI 同端口托管；个人 PWA 无需 SSR | Vite+React（可随时换）；双服务（留作升级路径） |
| 数据库/检索 | Postgres + pgvector（+FTS） | 多用户零迁移债、行级隔离、混合检索内建 | SQLite+sqlite-vec（迁移债）；LanceDB（多租户弱） |
| Embedding | 云 API（硅基流动 bge-m3 默认候选） | 省服务器资源、可扩多用户 | 本地 CPU（隐私优，未采纳；provider 接口保留可切换） |
| 文档解析 | PDF：pypdfium2 文本层快通道（默认）+ Docling 深度解析（按需）；其余格式：Docling | 快通道秒级/内存恒定（R7 事故复盘）；Docling 结构强但大 PDF 内存不受控（~14GB OOM） | pymupdf4llm（AGPL + 抽取准确率低）、PyMuPDF（许可/结构问题）、LlamaParse（付费 API） |

### 架构选择
- **结论**: 单体服务：FastAPI = 唯一运行时（REST API + SSE + 托管 web 静态产物）；Postgres 独立进程；入库解析走进程内后台任务（v1）。模块边界：`auth / documents / ingestion / retrieval / chat / storage`（全部可独立替换）。与 project.md §9 约束一致。
- **理由**: 单人 + 2C4G，进程越少越稳；模块边界 = 多用户留路（检索/存储/嵌入均为可替换接口）
- **备选方案及放弃原因**: 双服务（Next standalone + 反代）—— 功能无实际收益，运维成本高；多用户或前端独立扩展时再切换（同源代码支持）

### 数据模型决策
- 全实体携带归属字段 `owner_user_id`（单用户阶段固定值，查询自第一天按归属过滤）—— constitution VII 底线
- 内容块保存"标题路径 + 位置（页码/章节/段落）"以支撑 FR-006 出处；原文件独立存储、字节级保真（FR-013）
- 解析失败是一等业务状态（`unparseable`）而非异常（FR-014）
- 详见 [data-model.md](./data-model.md)

### 接口设计决策
- REST + SSE（流式回答）；下载走原文件端点；认证 = 会话 Cookie（HttpOnly）
- 详见 [contracts/api.md](./contracts/api.md)

### 增量设计（2026-10-01 增补 FR-015/016/017）
- **在线浏览（FR-015）**: 前端 `/view/` 页（PDF iframe / EPUB epubjs 渲染 / 文本视图）；原文件端点加 `inline=1` 内联参数（白名单格式）
- **出处跳转（FR-016）**: `/view/?id=&page=&q=&h=&from=` 参数协议；PDF `#page=`、文本高亮、EPUB CFI 精确定位 + 引文高亮（实现要点与踩坑记录见 research.md R6）；从对话进入可返回对话
- **用量记录（FR-017）**: LLM 请求 `include_usage` → messages.usage 落库 + done 事件携带 + 回答下方小字展示

### 增量设计（2026-10-02 试用增强）
- **检索融合修正（R15）**: 关键词加成限定向量候选（消除大文档"随机子集加成"）；`retrieval_keyword_boost` 0.05→0.12；候选池 top_k×3
- **既往对话引用的来源追溯（FR-020）**: `app/chat/inherit.py`——回写块内容定位原始回答消息（全文/前缀匹配）→ 继承其 citations；复制型回答向前找"引用条数 ≥ 文本最大标记"的最近助手消息；生成时（orchestrator）与读取时（conversation_messages，存量兜底）共用 `enrich_citations`；前端 [N] 映射 + 「回到原对话」深链（`/chat/?conv=&msg=`，复用滚动高亮）
- **存储占用展示**: `GET /api/stats/storage`（数据库/文件/快照分项 + 各来源计数）→ 资料页顶部小字展示
- **列表分页/搜索/排序（FR-018）**: `GET /api/documents` 信封化（`{items,total,page,page_size}`）+ `q/sort/page/page_size`；正文子串走既有 `ix_chunks_content_trgm`；前端工具条 + 页码条，查询状态进 URL（复用 `?source=` 模式）
- **对话搜索 + 侧栏收起（FR-019）**: `GET /api/conversations/search`（会话级聚合）+ `messages.content` trgm 索引（迁移 `d51a9c73e2b4`）；侧栏搜索防抖 + 点击定位高亮；收起状态 localStorage + 首屏脚本防闪跳（research R10）
- **深浅双模式**: `light-dark()` CSS + `:root[data-theme]` 手动覆盖 + 首屏内联脚本（跟随系统为缺省）
- **对话页可视化重做（as-built）**: 对齐 ChatGPT 风格——助手平铺正文/用户右侧灰气泡/组合式输入框/空状态（research R11）；引用 chip 的 `citation:` 协议在 react-markdown v10 下需自定义 `urlTransform`（research R12）
- **导航状态保真**: 列表/对话滚动位置与输入草稿 sessionStorage 记忆；返回链路（快照/阅读器→来源页）
- **检索稳健性修补（R16-R19，2026-10-02）**: `retrieval_ef_search`（默认 200）对全部检索查询生效（HNSW 删改 churn 召回退化兜底；维护流程 REINDEX+VACUUM 见 R16）；`_terms` 剔除纯数字词项（SVG 坐标假性加成，R17）；回写守卫过滤失败回答（R18）；**低置信多查询重试**（R19：无强命中时改写扇出扩检，`app/retrieval/rewrite.py`）

### 解析策略（R7，2026-10-01 事故复盘后调整）
- **PDF 快通道（默认）**: `pdf_fast.py`（pypdfium2 直抽 + 段落/断词/页眉页脚/字号标题启发式）；实测 1240 页 49 秒、内存 <500MB —— 大文件不再有 OOM 风险（原 Docling 全量 ~14GB 曾致宿主崩溃）
- **深度解析（按需）**: `reprocess?mode=deep` → Docling 分页批处理（120 页/批、默认关 OCR），表格/版面更完整、约 20 分钟
- **质量提示与恢复**: 表格占比 ≥8% → documents.parse_hint 提示"可深度解析"；批次间进度写 status_reason；启动扫尾标记中断任务为可重试

### 错误处理策略
- **业务状态 ≠ 异常**: 无法解析 → `unparseable` 状态 + 用户可见原因（不丢弃，FR-014）
- **外部依赖降级**: chat 模型故障 → 明确提示 + 可重试，历史与资料不受影响；embedding 故障 → 入库暂停并标记 `processing`，可重试
- **弱相关判定**: 检索分数低于阈值 → 模型兜底为主 + "库中可能相关"提示（spec FR-007）
- 统一错误响应格式（见 contracts/api.md）

### 测试策略
- **策略**: pytest 单元测试覆盖 解析/分块/检索/回写 核心路径；SC-001~008 做成可复跑的验收脚本（quickstart.md 场景）
- **理由**: 单人项目以"验收场景可复现"为最高优先级；不为覆盖率而测试；前端 v1 手工验收

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查结果 |
|------|---------|
| I. 文档结构合规 | ✅ 本 plan 全节遵循定制模板 |
| II. 决策留痕与调研先行 | ✅ 4 项决策经"调研 → 征询 → 记录"（research.md + 上表） |
| III. 文档语言 | ✅ 中文 |
| IV. 数据最小暴露 | ⚠️ **例外已登记**：云 embedding 使入库内容经服务商（用户知情决策，见 Complexity Tracking） |
| V. 数据可控 | ✅ 删除级联、原文件可下载（FR-011/013）；备份已具体化：本地每日 + 异地对象存储（SC-008） |
| VI. 可靠性优先 | ✅ 解析/入库与问答解耦；外部依赖故障降级明确 |
| VII. 单人规模，面向多用户留路 | ✅ owner 字段 / 可替换接口 / 认证边界 三条底线落进 data-model 与架构 |

**Gate 结论**: **PASS** —— 唯一例外（IV）已按 governance 要求登记于 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-core-qa/
├── spec.md          # 需求规格（含澄清）
├── plan.md          # 本文件
├── research.md      # Phase 0 调研 + 实现补记（R1-R6）
├── data-model.md    # 数据模型
├── quickstart.md    # 验证指南（SC-001~008 场景）
├── contracts/       # 接口契约
│   └── api.md
└── tasks.md         # 任务清单（44 项，已生成）
```

### Source Code (repository root)

```text
second-brain/
├── server/                      # Python 后端（单体 FastAPI）
│   ├── app/
│   │   ├── main.py              # 入口：API 挂载 + 静态产物托管
│   │   ├── auth/                # 认证（单用户白名单单账号 → 可扩多用户）
│   │   ├── documents/           # 上传 / 资料管理 / 无法解析登记 / 下载
│   │   ├── ingestion/           # 解析（pdf_fast 快通道 / Docling）+ 分块 + 云 embedding
│   │   ├── retrieval/           # pgvector + FTS 混合检索（可替换接口）
│   │   ├── chat/                # 对话编排：检索→生成(SSE)→兜底→回写
│   │   ├── conversations/       # 会话列表 / 消息读取 / 删除（FR-009/011）
│   │   ├── models/              # SQLAlchemy 模型（全表带 owner）
│   │   └── storage/             # 原文件存储抽象（本地磁盘实现）
│   ├── tests/                   # pytest + 验收脚本
│   └── pyproject.toml
├── web/                         # Next.js 前端（静态导出）
│   ├── app/                     # 登录 / 资料 / 对话 / 浏览（/view）
│   ├── public/                  # PWA manifest / icons / SW
│   └── package.json
├── deploy/                      # docker-compose（app + postgres）+ 部署说明
└── specs/                       # SDD 文档
```

**Structure Decision**: 前后端分目录（server/ + web/），生产部署时 `web/out` 静态产物由 FastAPI 托管 —— 单进程、同端口。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| IV. 数据最小暴露：入库阶段全部内容块经云 embedding 服务商 | 用户决策（2026-10-01）：省服务器 CPU、免本地模型维护、天然多用户扩展；已明确知悉并同意登记例外 | 本地 CPU embedding 隐私最优，但被用户权衡否决（资源与扩展性优先）；接口已抽象，将来可切回本地并后台重嵌入 |
