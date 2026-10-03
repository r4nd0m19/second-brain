# 契约：联网检索（库外兜底）

## 1. 组件协议（内部，可替换）

```python
class WebSearchClient(Protocol):
    async def search(self, query: str, count: int) -> list[WebSearchResult]: ...
    # 超时/HTTP 错误/解析失败 → 抛 WebSearchError（调用方降级）

def get_web_search() -> WebSearchClient | None:  # 未配置凭据 → None（能力关闭）
```

- 实现：`ZhipuWebSearch`（httpx；`POST https://open.bigmodel.cn/api/paas/v4/web_search`）；`SearXNGClient`（自托管元搜索，零成本，`paid=False`）；`DeepSeekWebSearch`（官方服务端 web_search 工具，token 计费，T086）
- 替换新供应商 = 新增实现 + 工厂切换，业务层零改动（FR-010）
- 决策器规则（2026-10-02 增补，FR-011）：用户显式发出联网/搜索指令且消息含可检索主题 → **必须触发**（即使模型自认能答）；无主题（"发起联网搜索"）→ 不触发；「搜一下我的资料」类本地检索意图 → 不触发；**概念/定义/原理/数学/代码/常识类通用知识问题 → 不触发**（即使模型自认细节不确定；防概念题随机联网，2026-10-02 收紧）

## 2. 外部依赖契约：智谱 Web Search API

| 项 | 值 |
|----|----|
| 端点 | `POST https://open.bigmodel.cn/api/paas/v4/web_search` |
| 鉴权 | `Authorization: Bearer <ZHIPU_API_KEY>`（**Bearer 直用**——2026-10-02 真实 key 实测通过，无需 JWT 签名） |
| 请求 | `{"search_query": str, "search_engine": "search_std", "count": 5, "content_size": "medium", "search_recency_filter": "noLimit"}` |
| 响应 | `{"id", "created", "search_result": [{"title", "link", "content"(摘要), "media"(站点名), "icon", "publish_date", "refer"}]}` |
| 错误 | 1701（搜索并发超限）/ 1702（无可用引擎）；HTTP 401（无效 key/欠费） |
| 计费 | `search_std` ￥0.01 / `search_pro` ￥0.03 / `search_pro_sogou` ￥0.05 / `search_pro_quark` ￥0.05（官方文档 2026-10-02 核对）；**按调用次数计费、与 count 无关** |
| count | 范围 1–50，默认 10（官方；本实现每次显式传值，首次取 `2×请求量` ≤50） |
| **link 字段语义** | 文档未定义；**实测按「引擎 × 查询」确定性缺失**（std/pro 对部分查询 0/5；sogou/quark 全覆盖）→ 客户端策略：2× 取样 + 只取有链接条目 + 主引擎零链接时**兜底引擎再试一次**（默认 `search_pro_sogou`；最坏成本 ￥0.06/次，常规仍 ￥0.01） |

### 2b. 外部依赖契约：DeepSeek 服务端 web_search（T086，可切换源）

| 项 | 值 |
|----|----|
| 端点 | `POST {LLM_BASE_URL}/anthropic/v1/messages`（默认 `https://api.deepseek.com/anthropic/v1/messages`） |
| 鉴权 | `Authorization: Bearer <LLM_API_KEY>` + `anthropic-version: 2023-06-01`（与对话同一 DeepSeek 账户） |
| 请求 | 声明服务端工具 `tools:[{"type":"web_search_20250305","name":"web_search","max_uses":2}]` + 提示词「请联网搜索：{query}（只要执行搜索、不展开回答）」+ `max_tokens=256` |
| 响应 | `content` 块序：`thinking` → `server_tool_use`(查询词) → `web_search_tool_result`（结果数组：`title`/`url`/`page_age`；正文为 `encrypted_content` 密文） → `text` |
| 计费 | **token 制**（无按次费）：按官方分档单价（含峰谷倍率）计入 web 成本；`usage.server_tool_use.web_search_requests` 为搜索次数 |
| 特性 | 模型自动改写/补全查询（常中英各一轮，单调用 1-2 轮搜索）；结果**无明文摘要**（密文仅模型可见）→ snippet 为空、重排按标题、正文由读页管线补齐 |
| 实测 | 单查询 ¥0.009–0.016；延迟 3.1–3.6s（直连搜索源的 ~10×）；质量对照见 001 R40/T086 |

## 3. 对话契约变更（对前端）

`POST /api/chat` 的 `meta` 事件（延续既有结构）：

- `source_type` 新增取值 **`web`**（联网作答；前端文案"来自网络"）
- `citations[]` 新增 web 形状：`{"document_id": null, "document_name", "source_url", "quote"(摘要), "web": true, "chunk_id": null, "heading_path": null, "page": null}`
- 前端行为契约：`web: true` 的来源 → 链接指向 `source_url`，**新标签打开**；出处列表按钮文案「↗ 打开网页」；不经过本地快照/阅读器路由（**2026-10-03/T087 补记**：回答内 `[N]` 角标点击改为弹「引文小窗」——展示标题/域名/`quote` 摘录与「↗ 打开原文」显式新标签；出处列表条目与「↗ 打开网页」按钮维持直开；小窗零新增接口）
- **混合引用**（2026-10-02 增补）：显式联网指令命中本地强相关时，同一条消息的 `citations` 可同时含本地与 web 条目——**本地在前（1..N）、web 续接（N+1..）**，`source_type=web`；前端按 `citations[N-1]` 映射编号，无需改动

## 4. 配置契约（.env）

| 键 | 默认 | 说明 |
|----|------|------|
| `WEB_SEARCH_API_KEY` | 空 | 空 = 能力关闭（不调决策器、零行为变化） |
| `WEB_SEARCH_MAX_RESULTS` | 5 | 单次搜索条数上限（成本控制） |
| `WEB_SEARCH_SNIPPET_MAX` | 800 | 单条摘要注入上限（字符） |
| `WEB_SEARCH_TIMEOUT_S` | 5.0 | 搜索超时（超时放弃联网） |
| `WEB_SEARCH_FRESHNESS` | noLimit | 时间范围（映射智谱 `search_recency_filter`） |
| `WEB_SEARCH_ENGINE` | search_std | 智谱引擎档位（std ￥0.01 / pro ￥0.03 / sogou·quark ￥0.05） |
| `WEB_SEARCH_FALLBACK_ENGINE` | search_pro_sogou | 主引擎零链接时的兜底引擎（空串=禁用；实测链接覆盖最好） |
| `WEB_SEARCH_DAILY_LIMIT` | 30 | 每日搜索次数上限（0=不限）；超限当天联网静默停用、问答照常（成本护栏） |
| `WEB_SEARCH_PROVIDER` | deepseek | 搜索源：`deepseek`（官方服务端搜索，token 计费；默认，T086）/`searxng`（自建免费）/`zhipu`（付费 API） |
| `DEEPSEEK_SEARCH_MODEL` | deepseek-flash | 服务端搜索调用所用模型 |
| `DEEPSEEK_SEARCH_TIMEOUT_S` | 30.0 | 服务端搜索超时（模型轮次 + 服务端检索，慢于直连源） |
| `DEEPSEEK_SEARCH_MAX_TOKENS` | 256 | 搜索轮输出上限（只搜不答，控成本） |
| `DEEPSEEK_SEARCH_BASE_URL` | 空 | 空 = 由 `LLM_BASE_URL` 推导（+ `/anthropic`） |
