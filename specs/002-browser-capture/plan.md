# Implementation Plan: F2 Windows 浏览器采集（browser-capture）

**Branch**: `002-browser-capture` | **Date**: 2026-10-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-browser-capture/spec.md`

## Summary

浏览即入库：Chrome/Edge（桌面，MV3）扩展在用户**真实阅读**网页时（停留 ≥10s 或滚动过半，可配置）于浏览器本地提取正文并生成高保真页面快照，异步上传到既有 FastAPI 服务，作为新来源类型（`browser`）进入 F1 的检索 / 问答 / 出处体系。支持黑名单（源头不采，含元信息）、一键暂停、同 URL 去重更新、离线队列重试、时间维度回找（元信息清单 + 语义×时间组合检索）与快照安全重现。硬约束：采集链路与 F1 问答完全解耦（constitution VI）、对浏览无可感影响、删除全链路生效（含快照与备份）。

快照引擎定稿 **single-file-core**（2026-10-02：用户决定取消原「先验证再定」的验证冲刺、直接采用推荐默认；引擎以单一接口封装保留替换路径，见 research R1）。

## Technical Context

**Language/Version**: Python 3.12（服务端，沿用）；TypeScript（扩展，MV3；esbuild 打包）

**Primary Dependencies**: 服务端沿用 FastAPI + SQLAlchemy(async) + pgvector（容器实核 0.8.6 ≥ 0.8，R5）+ 既有 ingestion 管线；扩展侧 @mozilla/readability 0.6.0 + defuddle（兜底）（R1）；快照引擎 single-file-core 1.6.20（定稿；接口封装保留替换路径，R1）

**Storage**: Postgres 16 + pgvector（documents 扩展列、capture_tokens 新表）；快照与正文文件沿用磁盘 BlobStore（`storage/{owner}/{doc}/`）

**Testing**: pytest（服务端单测 + acceptance）；扩展纯逻辑 Node + jsdom 单测（阶段②）；验证冲刺产出 20–30 样本体积实测记录；Windows 真机手动验收

**Target Platform**: 服务端 Linux（既有）；扩展 Chrome/Edge 桌面 MV3（Windows 为主）

**Project Type**: web-service + browser-extension（新增 `extension/` 组件）

**Performance Goals**: 浏览无可感影响（SC-006）；单页入库秒级（正文免重解析）；SC-001：阅读后 30 秒内可在对话中问出细节；检索不因新来源降级（沿用 F1 基线）

**Constraints**: 2C4G 服务器预算不变；单人规模（每天几十~数百页）；快照单页上限默认 20MB、上传并发 1–2（FR-014，可配置）；上传失败不影响浏览（FR-006）

**Scale/Scope**: 个人规模；沿用 F1 多用户留路（owner 过滤；token per-owner）

## 设计决策与理由 (Design Decisions & Rationale) *(mandatory)*

> 调研与来源见 [research.md](./research.md)（R1–R6）；本节为定稿结论。

### 技术栈选择
| 选择项 | 结论 | 理由 | 备选方案及放弃原因 |
|--------|------|------|--------------------|
| 扩展形态/构建 | 自研薄 MV3 扩展；TypeScript + esbuild | 需求高度定制（阅读阈值触发 / 黑名单 / 队列）；构建轻、无框架抽象 | wxt / vite 插件框架（抽象重）；纯 JS 免构建（依赖打包不便） |
| 快照引擎 | **single-file-core 内嵌**（定稿） | MV3 唯一成熟高保真路径（Karakeep 先例，R1）；用户取消验证冲刺后采用推荐默认；单一接口封装（`captureSnapshot()`）保留替换路径 | 纯自研快照（工作量成倍、保真低；若拒绝 AGPL 走接口替换）；Hoardy-Web / ArchiveWeb.page（debugger 横幅违无感）；MHTML（不能 HTTP 回放）；WARC（MV3 无低侵入生成） |
| 正文提取 | @mozilla/readability（克隆 DOM）+ defuddle 兜底 | 成熟、Apache-2.0、阅读模式同源引擎 | Postlight（已废弃）；纯自研（不必要） |
| 采集依赖许可 | 接受 single-file-core AGPL-3.0（已选用） | 自用 / 自托管无分发义务；将来公开分发时再面对（AGPL 兼容或替换内核） | 拒绝 AGPL → 接口替换为纯自研快照（保真与工作量代价大） |
| 服务端 | 沿用 FastAPI + Postgres/pgvector，不新建服务 | 采集与问答共用入库 / 检索 / 删除 / 备份链路（FR-010/VI：解耦指故障隔离而非物理分离） | 独立采集服务（2C4G 纯增运维，无必要） |
| 时间检索 | pgvector 迭代扫描（relaxed_order）+ B-tree 时间索引；不分区 | 10 万级最优；容器 0.8.6 已支持（R5） | 全精确扫描（慢、耗 CPU）；按月分区（百万级再评估） |
| 时间表达解析 | 规则优先 + 既有对话模型兜底（统一 JSON 契约） | 高频表达零延迟零幻觉；复用既有模型零新依赖（R6） | dateparser（中文 range 未证实）；Duckling（Haskell 服务过重）；纯规则 / 纯 LLM |
| 扩展认证 | 静态高熵 token（Bearer），服务端存哈希、可吊销、scope=capture | 单用户单客户端最优；OWASP 实践；不复用会话 cookie（R2） | 短期 token + refresh（MV3 刷新竞态，收益小）；OAuth / 设备码流（自建授权服务器过度设计） |
| 分发 | sideload 起步（商店 Hidden 为升级路径） | 开发迭代零成本；decision-consult 确认 | 商店上架（材料 + 过审，后置即可，无需改代码） |

### 架构选择
- **结论**: 采集端（扩展）→ 同一 FastAPI（token 认证的采集端点）→ 既有 BlobStore + documents/chunks → 检索 / 问答链路**零特殊对待**（FR-010，仅出处展示分支）。与 `.specify/memory/project.md` §9 一致（"采集端（F2 起）→ 同一 API → 入库"）。
- **理由**: 复用 F1 全部入库 / 检索 / 删除 / 备份能力；采集故障域与问答隔离（独立端点、独立后台任务、扩展侧队列——FR-009）。
- **备选方案及放弃原因**: 独立采集微服务（2C4G 上纯增运维）；扩展直连数据库（破坏安全边界）。
- **快照回放**: 同源但被 CSP `sandbox` 隔离的独立端点 + 前端空沙箱 iframe（R4）。

### 数据模型决策
- **网页条目 = documents 的 `source_type='browser'` 行**（复用 owner / 删除 / 备份 / 检索体系），扩展列：`source_url`（per-owner 唯一）、`first/last_captured_at`、`visit_count`、快照元数据（path/bytes/state）、`capture_id`（幂等）。详见 [data-model.md](./data-model.md)。
- **凭据 = capture_tokens 表**（哈希存储 + 前缀 + scope + revoked_at/last_used_at；scope 列为未来采集器复用留路）。
- **正文即入库源**：content.md → 轻量 Markdown 分块器（标题路径）→ 既有 embedding 管线；**浏览器来源不做 Docling 解析**（无重解析成本，入库秒级）。
- **黑名单 / 暂停 / 队列 = 扩展本地实体**（不上服务器）：源头不采 = 连黑名单元数据都不落库（FR-004 最彻底实现）；离线可用。
- **时间语义近似**：仅记首次 / 最近 + 次数（spec FR-011），不做访问事件表（Non-Goal：浏览行为分析）；已知局限记录于 data-model。

### 接口设计决策
- 采集接收 `POST /api/capture/pages`（token；multipart 字段与 SingleFile 官方扩展 REST 上传对齐——便于手工实测与降级采集路径）；`capture_id` 幂等键。
- 快照回放 `GET /api/documents/{id}/snapshot`（会话；CSP sandbox + gzip 直出）。
- 既有端点扩展：`GET /api/documents?source=upload|browser`、`DELETE /api/documents?source=browser&before/after`（时间清理）；凭据管理 `/api/capture/tokens`（会话）。详见 [contracts/capture-api.md](./contracts/capture-api.md)。
- Chat 出处扩展：browser 来源 citations 附 `source_url` / `last_captured_at`；时间意图在 orchestrator 前置解析（list 直出清单 / search 带过滤检索）。

### 错误处理策略
- **采集链路故障不影响 F1**（FR-009）：独立端点与后台任务；扩展侧"先落盘再发送" + alarms 退避重试，max 5 次进 dead-letter + badge 提示（R2）。
- **快照异常一律降级不阻塞**：超 20MB → 仅存正文 + 元信息（`skipped_oversize`）；生成 / 上传失败 → 队列重试，最终失败时正文照常入库（快照缺失可后补）。
- **入库校验**：URL 合法性、请求体天花板 100MB（防滥用）→ 400 / 413；幂等重复 → 200 duplicate（不重复计数）。
- **回放**：无快照 404；文件缺失 410（列表标注）；全部响应带 nosniff + CSP。
- 检索层错误处理沿用 F1（时间过滤失败 → 回退无过滤检索并在回答中标注）。

### 测试策略
- **策略**: ① pytest 单测 / 契约：token 认证与吊销、幂等、超限降级、时间过滤查询、回放响应头（CSP / Encoding）、清理端点；② acceptance 扩展（HTTP 实测）：SC-001/003/004/005/007/008 对应场景（含快照体积抽样记录，观测 20MB 上限命中）；③ 扩展纯逻辑 jsdom 单测（触发判定 / URL 规范化）；④ Windows 真机手动：sideload 安装、真实浏览无感（SC-006）、断网补传。
- **理由**: 沿用 F1 已验证的验收模式（HTTP 级 acceptance + 可复现脚本）；"无感"与"保真"只能在真机 / 真实数据上判定，留手动抽检，其余全部自动化。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 检查点 | 结论 |
|------|--------|------|
| I 文档结构合规 | plan 定制模板 + 设计决策节；research / data-model / contracts / quickstart 齐备 | ✅ |
| II 调研先行+留痕 | 3 路联网调研（R1–R6，含来源）；3 项选型经 decision-consult（快照引擎 / sideload / 20MB；引擎先定「验证」、后经用户决定取消验证、采用推荐默认 single-file-core） | ✅ |
| III 文档语言 | 中文文档，代码 / 标识符原文 | ✅ |
| IV 数据最小暴露 | 黑名单源头不采（本地表，含元信息不落库）；无痕不采；token 哈希存储 + scope=capture + 可吊销；扩展只连自建；快照文件仅自托管；回放 CSP sandbox 隔离（防其成为攻击面） | ✅ |
| V 数据可控 | 单条删除 + 时间范围批量清理（含快照，复用 BlobStore 目录级联）；备份镜像 `rsync --delete` 删除同步；token 可吊销 | ✅ |
| VI 可靠性优先 | FR-009 解耦：独立端点 / 任务 / 队列；F1 检索 / 问答 / 备份零改动路径 | ✅ |
| VII 多用户留路 | documents / capture_tokens 带 owner；token per-owner；检索 / 存储接口不变；scope 列为未来采集器留路 | ✅ |

**Gate 结论**: 无违反项；Complexity Tracking 空缺。（Phase 1 设计后复核：无新增违反。）

## Project Structure

### Documentation (this feature)

```text
specs/002-browser-capture/
├── plan.md              # 本文件
├── research.md          # Phase 0：调研结论（R1–R6 + decision-consult 结论）
├── data-model.md        # Phase 1：实体 / 字段 / 迁移
├── quickstart.md        # Phase 1：两阶段验收指南
├── contracts/           # Phase 1：采集 API 契约（含既有端点变更）
│   └── capture-api.md
└── tasks.md             # Phase 2（/speckit-tasks 产出，不在本次）
```

### Source Code (repository root)

```text
extension/                       # 新组件：MV3 采集扩展（TypeScript + esbuild）
├── manifest.json                # MV3；host_permissions=服务器 origin
├── src/
│   ├── background/              # SW：上传队列（storage 落盘优先）、alarms 退避、badge
│   ├── content/                 # 内容脚本：阅读度量（可见停留/滚动）、Readability、快照（idle/hidden）
│   ├── offscreen/               # 大对象上传（IndexedDB → offscreen document）
│   ├── shared/                  # 纯逻辑：触发判定 / URL 规范化 / 阈值（Node+jsdom 单测）
│   ├── popup/                   # 状态 + 暂停开关
│   └── options/                 # 服务器地址 / token / 黑名单 / 保存并测试
├── build.mjs                    # esbuild 打包
└── tests/                       # Node + jsdom 单测

server/
├── app/
│   ├── capture/                 # 新：采集接收（token 端点）+ 凭据管理（会话端点）
│   ├── documents/router.py      # 变更：source 筛选 / 时间范围清理 / snapshot 回放端点
│   ├── ingestion/webpage.py     # 新：网页正文入库（Markdown 分块 + embedding，免 Docling）
│   ├── retrieval/search.py      # 变更：时间过滤参数 + 迭代扫描
│   ├── chat/orchestrator.py     # 变更：时间意图解析（规则+LLM）+ list 直出
│   └── models/entities.py       # 变更：SourceType.browser、documents 扩展列、CaptureToken
├── alembic/versions/            # 新迁移（扩展列 + capture_tokens）
└── tests/                       # 单测 + acceptance 扩展

web/app/
├── page.tsx                     # 变更：来源筛选 / 时间清理 / 采集凭据管理区块
├── snap/page.tsx                # 新：快照安全回放页（空沙箱 iframe）
└── chat/page.tsx                # 变更：browser 出处渲染（标题/站点/时间 + 打开原文 + 查看快照）
```

**Structure Decision**: 扩展为独立顶层组件 `extension/`（独立构建链与测试；仅经 HTTP 契约与服务端耦合——FR-009 解耦的物理体现）；服务端 / 前端在既有结构内增量演进（新增 `server/app/capture/` 模块与 `web/app/snap/` 路由），不新建服务。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | | |
