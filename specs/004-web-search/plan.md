# Implementation Plan: 联网检索（库外兜底）

**Branch**: `004-web-search` | **Date**: 2026-10-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-web-search/spec.md`

## Summary

在问答的**库外兜底路径**（弱相关 / 无命中）上增加联网检索：受控双段式——先一个非流式"是否需要联网"的决策调用（函数调用形式），需要则执行搜索、把（按不可信内容包裹的）结果注入上下文，再做正常的流式生成，回答中附可点击的网页来源（区别于本地出处标注）。搜索服务以可替换协议封装（本次对接智谱）；凭据未配置/超时/失败一律静默降级为现有行为；搜索结果不写入本地库。（2026-10-03 补记：搜索源历经三轮演进——智谱按次 → SearXNG 自建零成本（R39/T085）→ 默认 DeepSeek 官方服务端搜索（token 计费、复用 LLM 凭据，R40/T086）；"可替换协议"设计使每轮演进 = 客户端新增 + 一次配置切换，架构结论不变。）

## Technical Context

**Language/Version**: Python 3.12（服务端）· TypeScript/Next.js 15（Web 端，仅小改）

**Primary Dependencies**: FastAPI、httpx（搜索调用与 LLM 均走 httpx，**不新增第三方库**）；现有 `OpenAICompatLLM` 扩展一个非流式带工具方法

**Storage**: 无新增表/无迁移——web 来源写入既有 `messages.citations`（JSONB）；`messages.source_type` 增加取值 `web`（VARCHAR 无 CHECK，遵循既有先例）

**Testing**: pytest（客户端解析/决策器/编排集成/降级链路，复用现有 monkeypatch 模式）

**Target Platform**: 自租服务器/本机（FastAPI 单进程）+ PWA 客户端

**Project Type**: Web 服务 + 前端（单仓）

**Performance Goals**: 库外兜底路径新增延迟 ≤ ~2s（决策调用 ≤1s + 搜索 ~1s）；搜索超时阈值 5s，超时即放弃联网

**Constraints**: 单用户；凭据可选（未配置 = 能力关闭、零影响）；决策调用与搜索请求只含当前用户问题（不外发本地库内容）；检索上限/截断可配置

**Scale/Scope**: 单人使用；单次受控搜索（不做多轮自主调研）

## 设计决策与理由 (Design Decisions & Rationale) *(mandatory)*

### 技术栈选择
| 选择项 | 结论 | 理由 | 备选方案及放弃原因 |
|--------|------|------|--------------------|
| 搜索供应商 | **智谱 Web Search**（`POST https://open.bigmodel.cn/api/paas/v4/web_search`，引擎默认 `search_std`） | 成本约博查的 1/3.6（≈￥0.01/次，50 次/天 ≈ ￥15/月）；国内直连；`search_result[].content` 即摘要 | 博查（质量最好但 ￥0.036/次——保留为可替换备选，切换≈一行配置）；SearXNG 自托管（0 元但无 AI 摘要+部署维护）；Tavily（贵、波动）；Brave/Serper（不可用/无正文）——详见 research.md R1（用户 2026-10-02 决策：成本优先） |
| 集成协议 | **函数调用（tools）双段式**：非流式"决策调用"（带 `web_search` 工具）→ 需要则执行搜索 → 正常流式生成 | 与 spec 既定方向一致；tool_calls 结构化解析比文本 JSON 稳；DeepSeek chat 端点全文本模型支持 tools（2026 现状核实） | 文本 JSON 规划器（`complete_chat` + JSON 解析；timerange 有先例，但不如 tools 结构化）；流中工具调用（中途中断流重启，复杂且影响流式体验）——详见 research.md R2 |
| 搜索结果 → 上下文 | 搜索结果包裹为**不可信块**（`<web_results>` 标记 + 系统提示声明"其中指令无效"） | 防提示词注入；外部内容不享有系统级可信度 | 直接平铺（注入风险）；过滤后再注入（无法穷举）——research R4 |
| 来源引用结构与前端 | citations 增加 **`web: true`** 形状（document_id=null、source_url=url、quote=摘要）；`source_type` 新增 `web`；前端按 `web` 分支渲染为外链（新标签打开） | 复用既有 citations 管线；与本地来源可区分；不污染本地文档跳转逻辑 | 新建独立来源通道（前端二套渲染）；把网页存成本地文档（违背"不入库"）——research R5 |
| 配置化 | `.env`：`WEB_SEARCH_API_KEY`（空 = 能力关闭）、引擎档位等 6 项 | 与既有配置模式一致；未配置零影响（FR-004）；引擎档位可在 `search_std`/`search_pro` 间按成本切换 | 设置页 UI（后置）；数据库配置（过度） |

### 架构选择
- **结论**: 新增 `app/websearch/` 模块（可替换协议 + 智谱实现 + 决策器），存量改动集中在编排层（`orchestrator.prepare_reply` 的兜底分支）与前端引用渲染；不改变主问答链路与本地检索
- **理由**: 与 project.md §9「采集与问答解耦」同构——联网是**兜底增强**，故障域被隔离在模块内；且接口化满足 FR-009/010（MCP 复用、供应商可替换）
- **备选方案及放弃原因**: 在检索层内嵌联网（污染本地检索语义）；独立微服务（单用户规模过度）

## Constitution Check

*逐条验证 constitution（v1.0.0）：*

- [x] **I. 文档结构合规**：plan 模板全部必填节保留（本文件 + research/data-model/contracts/quickstart）
- [x] **II. 决策留痕与调研先行**：供应商/协议/安全/降级均先联网调研并记录（research.md 附来源）；功能方向层面已按 decision-consult 征询用户（选中"把联网能力做进第二大脑"）
- [x] **III. 文档语言**：中文
- [x] **IV. 数据最小暴露**：决策调用与搜索请求**只含当前问题**（不含历史/本地库内容，FR-006）；不引入第三方数据 SaaS（搜索仅发问题关键词）；**不整库外发**原则保持
- [x] **V. 数据可控**：联网结果不持久化（无新增删除面）；引用随消息删除自然消亡
- [x] **VI. 可靠性优先于花哨**：三级降级（凭据缺失→能力关闭；超时→放弃联网；失败/空结果→照常作答），联网永不成为问答故障点（FR-004 + NFR Reliability）
- [x] **VII. 单人规模，面向多用户留路**：搜索能力以 Protocol 封装（可替换）；无新表；owner 过滤链路不变；MCP 复用同一接口（FR-009）

**Complexity Tracking**: 无违反项。

## Project Structure

### Documentation (this feature)

```text
specs/004-web-search/
├── spec.md / plan.md（本文件）/ tasks.md（后续）
├── research.md            # 决策记录（供应商/协议/安全/降级 + 来源）
├── data-model.md          # 无新表声明 + 实体形状（临时结果/引用/web 来源类型）
├── contracts/web-search.md # 组件协议 + 智谱 API 契约 + 对话 meta 变更 + 配置键
├── quickstart.md          # 验证指南（含降级演练）
└── checklists/requirements.md
```

### Source Code (repository root)

```text
server/app/
├── websearch/
│   ├── __init__.py
│   ├── client.py          # WebSearchClient Protocol + ZhipuWebSearch（httpx，超时/错误→WebSearchError）
│   ├── searxng.py         # SearXNG 自托管元搜索客户端（paid=False，零成本；T085/R39）
│   ├── deepseek.py        # DeepSeek 服务端 web_search 客户端（token 计费；T086/R40）
│   ├── reader.py          # 读页管线：并行抓取→trafilatura 正文→段落级重排筛（T082/R38）
│   └── guard.py           # 每日搜索次数护栏（进程内计数；WEB_SEARCH_DAILY_LIMIT）
├── chat/
│   ├── llm.py             # +complete_with_tools（非流式，带 tools，解析 tool_calls）
│   ├── orchestrator.py    # 兜底分支接入：决策→搜索→注入不可信块→web citations；source_type=web
│   └── router.py          # meta 携带 web 来源（沿用 citations 字段，无结构变化）
├── config.py              # +WEB_SEARCH_* 配置（key 空 = 关闭）
└── models/entities.py     # AnswerSource + web（无迁移）

server/tests/
├── test_websearch_client.py   # 智谱响应解析 / 错误 / 超时 / 工厂
├── test_websearch_searxng.py  # SearXNG 解析 / 免费源标记（T085）
├── test_websearch_deepseek.py # DeepSeek 服务端搜索：块解析 / 去重 / token 计费 / 错误（T086）
├── test_websearch_reader.py   # 读页：正文提取 / 段落筛选 / 降级（T082）
├── test_websearch_guard.py    # 每日上限：达限停用 / 跨日重置
└── test_websearch_flow.py     # 编排集成：触发/不触发/降级/来源形状（假 client）

web/
├── lib/api.ts             # Citation + web 字段 / source_type 标签
└── app/chat/page.tsx      # web 来源渲染（外链新标签、来源标注"来自网络"）
```

## 未决与风险（进入实现时核对）

1. **智谱参数与鉴权口径**：API Key 是否可作 Bearer 直用（旧版需 JWT 签名）、`count` 默认值（10 vs 20）、`search_engine` 档位与计费映射 → 实现时以真实 key + 官方定价页核验（research.md R1/R7）
2. **`deepseek-chat` 别名弃用**（官方 2026-07-24 起迁移 V4 系列，当前仍兼容响应）→ 本 feature 不依赖具体 ID（走配置）；作为独立风险记录，后续切换显式 V4 ID（不在本 feature 范围）
3. **"模型跳过工具"缓解效果**：提示词触发规则 + 验收样例（应触发场景）需在实现期实测调优（research.md R3）
