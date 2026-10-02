# Phase 0 Research — F2 Windows 浏览器采集（browser-capture）

> 调研方式（constitution II）：3 路联网调研（① 扩展技术路线；② 扩展连接/认证/分发；③ 服务端快照存储与时间检索），2026-10-02。全部完成。
> R1/R2 关键选型经 decision-consult；其中快照引擎的「先验证再定」后经用户决定取消，采用推荐默认（见 R1 决策）。其余为调研直证 + 工程默认值（可配置项在 plan 中标注）。

## R1 采集扩展技术路线（2026-10-02）

**决策（2026-10-02；初议「先验证再定」，当日用户决定取消验证、直接采用推荐默认）**: 自研薄 MV3 扩展（阅读触发 + 队列 + 上传 + Readability 正文提取），快照生成**内嵌 single-file-core**（MV3 唯一成熟高保真路径，Karakeep 先例；npm 实核 `1.6.20`）。保留退出路径：快照生成在扩展内封装为**单一接口**（如 `shared/snapshot`，`captureSnapshot(): Promise<Blob>`），若后续拒绝 AGPL 或效果不满，替换内核不动其余代码。不改造 Hoardy-Web / ArchiveWeb.page；快照格式选 **SingleFile 式单文件 HTML**（WARC/WACZ 列远期备选；MHTML 出局）。

- **正文提取**: @mozilla/readability（0.6.0，Apache-2.0）对克隆 DOM 解析（`document.cloneNode(true)`，避免改动用户页面）；`isProbablyReaderable()` 预检；defuddle（MIT）作空/过短 fallback（其在 SW 环境的稳定性报告不一致，内容脚本内使用）。Postlight Parser 弃用（deprecated）。SPA：阈值达标先 parse，空/过短则 MutationObserver"静默窗口"（1–2s 无变更）重试，总上限后降级只存元信息；SPA 路由切换用 `chrome.webNavigation.onHistoryStateUpdated` 重置测量（内容脚本隔离世界观察不到 pushState）。已知坑：Readability 不递归 shadowRoot；SSR 流式 hydration 的隐藏内容可能被剥掉。
- **快照引擎**: single-file-core（SingleFile 官方核心的独立 npm 包，MV3 已验证——Karakeep 官方扩展内置"client-side crawling powered by SingleFile"）；运行时 `getPageData(options)` → `{content, title, filename}`。**生成时机: `requestIdleCallback` 或 `visibilitychange→hidden`/`pagehide`**（回放期取资源 + 去重选项会明显拖慢页面，避开可见交互期）。
- **触发与上传链路**: 内容脚本测**可见停留**（Page Visibility API 仅可见时累计）≥10s **或最大滚动深度** ≥50%（节流 scroll / IntersectionObserver 底部哨兵）；达标 → SW 层 IndexedDB 队列 → 快照 → **offscreen document 上传**（并发 1–2 + 指数退避；大 Blob 不走 chrome.* 消息——64MB 上限）。SW 不做 keep-alive（Chrome 明确不提供持久 SW），用 `chrome.alarms` 唤醒补传；大对象一律 IndexedDB（`chrome.storage.local` 默认仅 10MB）。
- **体积治理（生成端）**: blockScripts、removeHiddenElements、removeUnusedStyles/Fonts、compressHTML、`groupDuplicateImages`（重复图可减 30–60%）、removeFrames、图片降采样；超限**降级为仅正文**。扩展内 `CompressionStream('gzip')` 压缩后上传（Bandwidth + 服务端按 R3 原样存 gz 直出）。
- **许可注意**: single-file-core 为 **AGPL-3.0** —— 个人自用/自托管义务极轻；若将来**公开分发**扩展，需整体 AGPL 兼容或 clean-room 自研序列化（v1 不做）。Readability 为 Apache-2.0。（npm 实核 2026-10-02：`single-file-core@1.6.20` AGPL-3.0-or-later；`@mozilla/readability@0.6.0` Apache-2.0。）

**理由**: MV3 下 `chrome.debugger` 方案（Hoardy-Web、ArchiveWeb.page 路线）会在所有窗口常驻"扩展正在调试此浏览器"横幅，与"浏览无感"（SC-006）硬冲突，直接排除；WARC/WACZ（保真最高、体积最省）在 MV3 拿不到响应体（webRequest 读不到 body），生成端无低侵入路径；MHTML 受 Chromium 限制只能从文件系统加载且强制 sandbox（脚本禁用），**不能 HTTP 直出回放**，不满足自托管回放；"仅 DOM 序列化"无资源不可"重现"。SingleFile 单文件 HTML 是"扩展内可生成 + 自托管可直出回放 + 高保真"三者同时成立的唯一方案。Hoardy-Web 裁剪成本高：GPLv3+、Firefox 优先、Chromium 靠 debugger 兜底（随机脱离、大文件缺陷）、构建目标仍 MV2、无"阅读阈值"语义。

**备选方案及放弃原因**: SingleFile 官方扩展 + 其 REST Form API 上传（v1.22.54+；auto-save 按 load/unload 触发，**无法实现停留/滚动过滤** → 曾拟作验证冲刺工具（2026-10-02 取消），仍可用作手工实测 / 降级采集路径）；ArchiveWeb.page 裁剪（debugger 横幅 + AGPL + 组件重）；服务端 CDP 抓取（非被动、登录态/动态页不保真，只可作公开页降级路径）；WACZ 回放栈（远期备选）；Gwtar（2026 新动向，观察项）。

**来源**: SingleFile <https://github.com/gildas-lormeau/SingleFile> 与 single-file-core <https://github.com/gildas-lormeau/single-file-core>；getPageData API <https://github.com/gildas-lormeau/SingleFile/discussions/1055>；Karakeep SingleFile 集成先例 <https://docs.karakeep.app/integrations/singlefile/>；Hoardy-Web 缺陷说明 <https://oxij.org/software/hoardy-web/tree/master/extension/README.md>；chrome.pageCapture MHTML 限制 <https://developer.chrome.com/docs/extensions/reference/api/pageCapture>；@mozilla/readability <https://github.com/mozilla/readability>；defuddle <https://github.com/kepano/defuddle>；MV3 SW 生命周期与 offscreen <https://developer.chrome.com/docs/extensions/develop/migrate/known-issues>、<https://developer.chrome.com/blog/offscreen-documents-in-manifest-v3>；SingleFile 体积治理选项 <https://github.com/gildas-lormeau/SingleFile/issues/578>

## R2 扩展连接、认证与分发（2026-10-02）

**决策**: **静态高熵 API token**（每设备一枚，`Authorization: Bearer`），服务端只存哈希 + 前缀、可吊销；扩展网络请求**全部走 SW**（`host_permissions` 静态声明）；上传队列"**先落盘再发送 + alarms 退避 + 幂等键**"；分发 sideload 起步（商店 Hidden 列为升级路径）；配置放独立 options 页。

- **认证**: token 随机高熵（`sb_cap_` 前缀 + 32B 随机），服务端存 `SHA-256(token)` + 可识别前缀 + `revoked_at`/`last_used_at`；权限边界 = 仅挂载在采集端点。**不复用 web 会话 cookie**（扩展 SW 请求非 same-site，SameSite=Lax 的会话 cookie 根本不会带上——双重理由）。凭据存 `chrome.storage.local`（官方明确其**不加密**：威胁模型 = 本机 profile 泄露，故 token 权限收窄到仅采集写）+ `setAccessLevel('TRUSTED_CONTEXTS')` 防 content script 读取；不用 storage.sync（会同步到账号）。
- **CORS**: `host_permissions` 精确覆盖 API origin 后，**SW fetch 不做 CORS 检查、不发 OPTIONS 预检**（Chromium 源码级证据：allow-list 命中即跳过 CORS 与预检）；**content script 不享受豁免**（Chrome 85+ 受宿主页约束）→ 所有网络请求放 SW。注意：POST 会带 `Origin: chrome-extension://<id>` 且不可去除 → **服务端不做严格 Origin 白名单**；host_permissions 写**最终** origin（避免 http→https 重定向后重新判定）；保留极简 OPTIONS/ACAO 兜底（成本≈0）并开发期实测。
- **可靠上传队列**: 采集 payload（正文 + 元数据原子写 `chrome.storage.local`；**快照大对象走 IndexedDB**）——先落盘、后发送；fetch 短超时（官方硬约束：**响应 >30s 杀 SW**）；`chrome.alarms`（最小 0.5min）指数退避 1→60min、max 5 次进 dead-letter + badge 提示；**`Idempotency-Key`**（客户端 per-capture UUID）服务端去重，重试/重发不产生重复条目与重复计数；监听器全部顶层注册、不依赖全局内存态；SW 启动时重建 alarm。
- **分发**: dev/unpacked sideload（Chrome 134+ 起**开发者模式必须常开**）；长期稳定：**Edge Partner Center Hidden（免费）** 或 **CWS unlisted（$5 一次性）**，均带自动更新（Edge 过审 ≤7 个工作日）；企业策略强制分发路线（需域管理）个人不适用。（decision-consult 2026-10-02 确认：**先 sideload 起步**，商店 Hidden 为上架升级路径。）
- **设置体验**: 独立 options 页（Server URL + token + "保存并测试"）；URL 校验仅 `https://` 或 loopback；连接验证两步：`GET /health`（可达性）→ 受鉴权轻端点（token 有效性，401/403 区分）；`runtime.onInstalled` 首次自动打开 options；badge 三态（绿=正常/黄=队列积压/红=鉴权失败）+ popup 显示队列深度与最近错误。

**理由**: 单用户单客户端下短期 token + refresh 的复杂度（MV3 SW 刷新竞态）换不到实质安全增益，自托管先例（Karakeep/Joplin）即静态 token + 服务端哈希存储（OWASP 实践：只存哈希、show once、header 传递、按 key 限流与 last_used、吊销即时生效）；"先落盘再发"是 MV3 硬约束（SW 30s 空闲被杀、in-flight fetch 不保证完成）；`chrome.alarms` 是唯一跨挂起的定时器机制。

**备选方案及放弃原因**: 短期 access + refresh token（多客户端/共享设备场景才有意义）；设备码流 RFC 8628 / OAuth device flow（需自建授权服务器，单用户自建过度设计）；企业策略强制安装（需 AD/域环境）；纯事件驱动 flush 队列（实现简单但可靠性弱，留作降级形态）。

**来源**: Chrome storage 文档（含 local 不加密与 setAccessLevel）<https://developer.chrome.com/docs/extensions/reference/api/storage>；Chromium `cors_url_loader.cc` / `cors_util.cc`（host permission 豁免 CORS）<https://github.com/chromium/chromium/blob/main/services/network/cors/cors_url_loader.cc>；官方跨域网络请求文档 <https://developer.chrome.com/docs/extensions/develop/concepts/network-requests>；SW 生命周期 <https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle>；chrome.alarms <https://developer.chrome.com/docs/extensions/reference/api/alarms>；OWASP REST Security Cheat Sheet <https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html>；Karakeep API key 先例 <https://docs.karakeep.app/api/karakeep-api/>；CWS 分发与注册 <https://developer.chrome.com/docs/webstore/cws-dashboard-distribution>、<https://developer.chrome.com/docs/webstore/register>；Edge 注册（免费）与 Hidden 发布 <https://learn.microsoft.com/en-us/microsoft-edge/extensions/publish/create-dev-account>、<https://learn.microsoft.com/en-us/microsoft-edge/extensions/publish/publish-extension>；Chrome 134 unpacked 限制 <https://support.google.com/chrome/a/answer/10314655>

---

## R3 快照存储形态与体积治理（2026-10-02）

**决策**: 快照字节存**宿主机磁盘**，Postgres 只存元数据；不引入对象存储、不用 BYTEA。

- **布局**：沿用既有 BlobStore 模式 `server/data/storage/{owner}/{doc_id}/`，快照固定名 `snapshot.html.gz`（sha256 记 DB 行）；正文 Markdown 同目录 `content.md`（入库源 + 快照缺失时的降级产物）。
- **压缩**：落盘即 gzip（标准库）；回放端点以 `Content-Encoding: gzip` **原样流式返回**，服务端零解压。
- **单页体积上限**：默认 20MB（`capture_snapshot_max_mb` 可配置，FR-014；decision-consult 2026-10-02 确认默认值）；超限**降级**为"仅正文 + 元信息"，标注快照未保留（快照生成失败/超限不阻塞入库）。
- **备份与删除**：`server/data/storage/` 已在 `deploy/backup` 的 storage-mirror（`rsync --delete`）范围内 —— 快照自动纳入备份、删除自动同步（constitution V，无需改备份脚本）。
- **容量预期**（决策依据）：30 页/天 × 均值 ~2MB ≈ 原始 ~1.8GB/月（gzip 后更小，图片占比决定）；长尾媒体页（Reddit 类 20–30MB+）由上限截断。

**理由**: BYTEA 走 TOAST（>2KB 压缩+分块存储、整值读取需重组、WAL/备份放大，官方文档明示大文件应走文件系统）；个人规模上 MinIO 只增加 2C4G 运维成本；磁盘一致性问题用"先写文件、后提交 DB 行"顺序 + 既有目录级联删除语义解决。

**备选方案及放弃原因**: BYTEA（放弃：整值重组、pg_dump/备份膨胀）；MinIO/对象存储（放弃：收益在多机/异地场景，属未来，服务器同厂对象存储延后决策已有先例 R8）；sha256 内容寻址分片 `data/snapshots/ab/cd/<sha>.html.gz`（放弃：个人规模去重收益极小——同 URL 覆盖更新、不同 URL 同内容罕见；且删除需引用计数/GC，与既有"目录级联删除 + 镜像同步"语义冲突）。

**来源**: SingleFile 体积数据点 <https://github.com/gildas-lormeau/SingleFile/issues/1532>；Postgres TOAST 官方文档 <https://www.postgresql.org/docs/current/storage-toast.html>；pgsql-general 文件存储共识 <https://www.postgresql.org/message-id/4BD6A637.8030902%40hogranch.com>；Documenso 存储配置 <https://docs.documenso.com/docs/self-hosting/configuration/storage>

---

## R4 快照安全回放（2026-10-02）

**决策**: 把归档 HTML 视为**永远不可信**，安全边界放在**响应头 CSP + iframe 空沙箱**，不做"依赖净化"。

- **回放端点**：`GET /api/documents/{id}/snapshot`（需登录会话），响应头：
  - `Content-Security-Policy: sandbox; default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; media-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'`
  - `X-Content-Type-Options: nosniff`；`Content-Type: text/html`；不带任何可被页面读取的凭据上下文（CSP `sandbox` 使文档进 opaque origin，即使被直接开成顶层页也受限）。
  - SingleFile 快照资源已 data: 内联，`default-src 'none'` 天然阻断残余外链请求（防 IP/行为泄露），无需自建重写代理。
- **前端**：`<iframe sandbox="" src=...>`（空值 = 禁脚本/表单/弹窗/下载/顶层跳转/同源存储）；"打开原文"按钮外链原始 URL。
- **防御纵深**（可选、非安全边界）：入库时尽力剥离 `<script>` 与 `on*` 属性；不依赖它。
- **会话 Cookie 维持 host-only**（已核对 2026-10-02：`set_cookie` 未设 `domain`，host-only + HttpOnly + SameSite=Lax；未来若配独立子域回放，同样因 host-only 不跨子域）。

**理由**: 行业共识 = 回放页可能执行恶意 JS（ArchiveBox 文档明示，其维护者拒绝"同域共享 cookie 重放"并视为高危）；MDN 明确 `allow-scripts + allow-same-origin` 组合"强烈不建议"（被嵌页可自行移除 sandbox）——Open WebUI 的 stored XSS（GHSA-4vrc-m9ch-6m3r）即此组合所致；归档回放学术分类中 **sandboxed replay**（pywb framed replay）为安全推荐；Wayback/pywb 的 WARC+Service Worker+wombat 全套为高保真动态回放设计，对 SingleFile 静态快照过重。

**备选方案及放弃原因**: pywb / ReplayWeb.page / WACZ（放弃：组件重、AGPL、为动态回放设计；个人静态快照不需要）；独立回放子域（更强隔离，保留为部署期可选加固；CSP sandbox + 空 iframe 下风险已可接受）；以 DOMPurify/nh3 净化作为唯一防线（放弃：净化必然损失保真且不是安全边界）。

**来源**: MDN iframe sandbox <https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe>；MDN CSP sandbox <https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox>；ArchiveBox 安全指引 <https://docs.archivebox.io/v0.4.24/Publishing-Your-Archive.html> 与 #724；pywb framed replay（security）<https://github.com/webrecorder/pywb/blob/master/docs/manual/configuring.rst>；Open WebUI GHSA-4vrc-m9ch-6m3r；rrweb sandbox 设计 <https://github.com/rrweb-io/rrweb/blob/master/docs/sandbox.md>

---

## R5 时间过滤的混合检索（pgvector）（2026-10-02）

**决策**: 在既有 `hybrid_search` 增加可选时间范围参数；采用 pgvector 迭代扫描适配"先过滤后取 top-k"。

- **索引**：`documents(source_type, last_captured_at)` B-tree（时间过滤选择性走这里）；chunks 沿用既有 HNSW。
- **查询写法**（pgvector ≥ 0.8）：向量分支追加 `document_id IN (SELECT id FROM documents WHERE owner=... AND source_type='browser' AND last_captured_at >= :start AND < :end)`；会话内 `SET LOCAL hnsw.iterative_scan = relaxed_order`、`hnsw.ef_search = 100`；如需严格距离序用 MATERIALIZED CTE 再排。关键词分支同样追加过滤。
- **规模**：10 万级**不做分区**（迭代扫描 + B-tree 足够）；1–2M 行再评估按月分区 + 每分区 HNSW。
- **版本核对（已完成 2026-10-02）**：本机容器 pgvector 扩展 = **0.8.6**（≥ 0.8，`hnsw.iterative_scan` 可用）。
- **列表意图**（"我上周看过哪些网页"）**不走向量检索**：直接 SQL 列 `documents`（标题 + URL + 时间）→ 模板/LLM 润色成清单回答。
- **验证**：每条新查询 `EXPLAIN ANALYZE` 确认索引路径（实现任务内执行）。

**理由**: HNSW 的 WHERE 是索引扫描后过滤——官方例：过滤命中 10%、`ef_search=40` 时平均只剩 4 行（overfiltering）；0.8.0 的迭代扫描（上限 `max_scan_tuples` 默认 20000 ≈ 全库 20%）正是为此设计；一周窗口在数月数据中约 5–20% 选择性，属迭代扫描甜区；10 万级精确扫描 110–500ms（硬件差异大）吃 CPU，HNSW 毫秒级且 2C4G 上要给对话留资源。

**备选方案及放弃原因**: 全精确扫描（10 万行可用但偏慢，留作索引失效兜底）；oversampling 再过滤（选择性强时需 10× 候选，等于扫大半索引）；partial HNSW 索引（适合稳定低基数过滤值如 owner，时间值持续增长不适合）；按月分区（当前规模收益为负，留待百万级）。

**来源**: pgvector README（Filtering / Iterative index scans — <https://github.com/pgvector/pgvector>）；pgvector 0.8.0 发布公告 <https://www.postgresql.org/about/news/pgvector-080-released-2952/>；Crunchy Data 混合检索 <https://www.crunchydata.com/blog/hybrid-vector-search>；Tigerdata 时间过滤教程 <https://www.tigerdata.com/blog/refining-vector-search-queries-with-time-filters-in-pgvector-a-tutorial>

---

## R6 中文相对时间解析（自然语言 → 时间范围）（2026-10-02）

**决策**: **规则优先 + LLM 兜底**，统一产出结构化契约，服务端校验后转半开区间过滤。

- **契约**（Pydantic 校验）：`{start, end, granularity, confidence, intent}`；`intent ∈ {list, search, none}`（"看过哪些"= list；"看过的文章里关于 X"= search；无时间表达 = none）。
- **规则层**（零延迟、零幻觉，覆盖高频表达）：今天/昨天/前天、本周/上周、最近 N 天 / N 天前（含中文数字）、上个月、今年等；时区固定 Asia/Shanghai；锚点 = 收到消息的时刻；半开区间 `[start, end)` 防边界重复；"N 天前看的那篇文章"类只切出时间片，剩余文本作检索关键词。
- **LLM 兜底层**：仅当规则未命中 / 多表达 / 模糊（"上个月底"）时调用既有对话模型；prompt 显式给当前时间（含时区）+ 星期 + 原句，要求严格 JSON（优先 structured output）。
- **校验与纠错**: `start ≤ end`、跨度上限 5 年、低置信或未来时间不静默使用（回退无过滤或反问）；解析结果在回答中**回显**（"统计 9-21 ~ 9-27"）便于用户纠正。
- **时间字段**：过滤 `documents.last_captured_at`（v1 只记首次/最近 + 次数，不做访问事件表——已知近似局限：同页跨窗口多次访问按"最近"归属，记录于 data-model）。

**理由**: 规则层保证高频表达稳定，LLM 只处理长尾（规则+LLM 是时间解析研究常见混合架构）；复用既有对话模型零新依赖。

**备选方案及放弃原因**: dateparser（中文 time-span 能力未文档化，不可作主方案）；Duckling（官方支持中文，但需独立 Haskell 服务，2C4G 不划算）；mcp-chinese-time（表达清单可借鉴，项目新不押注）；纯规则（长尾覆盖不足）；纯 LLM（高频表达引入不必要延迟与幻觉面）。

**来源**: dateparser 文档 <https://dateparser.readthedocs.io/en/latest/>；Duckling 中文支持 <https://github.com/facebook/duckling/pull/523>；LLM 时间范围 JSON schema 参考 <https://arxiv.org/pdf/2601.09523v1.pdf>；规则+LLM 混合解析 <https://zenodo.org/records/16352283>；mcp-chinese-time <https://glama.ai/mcp/servers/wyl116/mcp-chinese-time>

---

## 未决项（留给实现阶段）

1. **快照压缩实测**：gzip 对真实 SingleFile 快照的整体压缩率依赖图片占比 —— 验收期基于 `snapshot_bytes` 抽样观测，必要时调上限默认值（R3；非定稿门槛）。
2. **snapshot 端点 CSP 细节微调**：按 SingleFile 内联资源形态（data: 图片/字体/样式）实测渲染完整性（R4）。
3. **扩展侧快照生成选项**：single-file-core 的脚本处理 / 体积治理选项名与默认值以实现时核对其代码与文档为准（R1）。

（已解决：pgvector 版本核对 → 0.8.6，R5；会话 Cookie host-only → 已核对，R4。）
