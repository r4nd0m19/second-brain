# Phase 0 Research — F1 核心问答（core-qa）

**Date**: 2026-10-01 | **方式**: 联网调研（constitution 原则 II 调研先行） | 每节含 Decision / Rationale / Alternatives

## R1 技术路线：自研 vs 开源二开

- **Decision**: 自研（组件搭建）
- **Rationale**: spec 的多个行为（兜底回写闭环 FR-008、无法解析登记 FR-014、原文件字节保留 FR-013、资料/对话界面分区）在现成开源产品中都要改分叉；本项目为长期个人基础设施，代码可控优先
- **Alternatives**:
  - Khoj（AGPL 传染许可；交互模型与 spec 有差异）
  - AnythingLLM（MIT 但 workspace 产品模型与 spec 分区冲突）
  - Open WebUI（品牌许可条款 + 官方承认 RAG 有局限）
  - Onyx（企业向，过重）
- **Sources**: [zimaspace 2026 自托管对比](https://shop.zimaspace.com/blogs/tech-ai-hub/top-10-open-source-ai-assistants-you-can-self-host)、[sumshare RAG 平台横评](https://www.sumshare.cn/blog/2026/09/19/sme-rag-platforms/)、[Onyx 自托管 RAG 指南](https://onyx.app/insights/self-hosted-rag)

## R2 技术栈：Python × Next.js 混合（单进程）

- **Decision**: FastAPI（后端 + 全部业务逻辑）+ Next.js 静态导出（前端 PWA，由 FastAPI 同端口托管）
- **Rationale**: Python 拿走 RAG 全链路生态（**Docling 仅 Python**）；Next.js 拿走前端体验；个人 PWA 不需要 SSR；单进程 = 无 Node 运行时/CORS/反代，2C 服务器最稳；将来可切 Next standalone 双服务（同源代码支持）
- **Alternatives**:
  - 纯 TS 全栈（文档解析生态弱）
  - 双服务独立部署（两个进程 + 反代，对单人项目重）；已记录为升级路径
  - Vite+React 替代 Next（架构不变，可随时换，未选为保持 Next 生态）
- **Sources**: [Xinference Next.js 静态导出单进程实践](https://blog.gitcode.com/f9527af8522d9029f988b63131aeda85.html)、[Vercel Services 2026](https://vercel-docs.vercel.sh/docs/services)、[Next.js+FastAPI nginx 实操坑位](https://dev.classmethod.jp/articles/nextjs-fastapi-nginx-subpath-routing-pitfalls/)

## R3 向量检索：Postgres + pgvector

- **Decision**: PostgreSQL 16 + pgvector（HNSW）+ 内建 FTS（混合检索）
- **Rationale**: 面向多用户扩展的零迁移债（constitution VII 底线：行级归属隔离、并发、成熟备份）；结构化数据与向量同库；FTS 内建（中文可选 zhparser/pg_trgm，实现阶段定）
- **Alternatives**:
  - SQLite + sqlite-vec（单机最简、备份=拷文件；但多用户化需迁移，**备选保留**）
  - LanceDB（真 ANN + 原生混合，但多租户非其设计重心）
- **服务器规格**: 2C4G 起步（Hetzner CX22 €3.79/月 即 4G；国内轻量 2C4G 档）
- **Sources**: [D-Central 自托管向量库对比 2026](https://d-central.tech/self-hosted-vector-databases/)、[sumshare 向量库横评](https://www.sumshare.cn/blog/2026/09/20/vector-db-landscape/)

## R4 Embedding：云 API（含 constitution 例外）

- **Decision**: 云 embedding API —— 默认候选硅基流动 bge-m3（免费、国内直连）；备选阿里云百炼 text-embedding-v4（¥0.5/百万 tokens）
- **Rationale**: 用户权衡决策（2026-10-01）：省服务器 CPU、免本地模型维护、天然可扩多用户
- **⚠️ 例外**: 与 constitution IV「不整库外发」冲突 —— 入库阶段全部内容块将发送给 embedding 服务商；已在 plan.md「Complexity Tracking」登记
- **Alternatives**: 本地 CPU 开源模型（fastembed/bge-small-zh；隐私最优，未采纳）
- **Sources**: [Embedding API 指南 2026](https://ofox.ai/zh/blog/embedding-api-rag-guide-2026/)、[AI API 价格对比](http://aipricing.org/compare?models=bge-m3,qwen3-embedding-8b,text-embedding-3-small)

## R5 文档解析：Docling

- **Decision**: Docling（MIT）作为主力解析器
- **Rationale**: 结构保留最强（DoclingDocument AST + HybridChunker 按标题路径分块，直接服务 FR-006 出处定位）；PDF/EPUB/DOCX 全覆盖；纯本地运行；扫描件可检测（支撑 FR-014 判定"无法解析"）
- **Alternatives**:
  - PyMuPDF / PyMuPDF4LLM（快，但许可表述混乱 + 无结构 + 扫描件静默返回空）
  - pdfplumber（慢、需自写结构后处理）
  - LlamaParse（按页付费 API，隐私与成本不符）
- **补充**: 大文件解析走后台任务，不阻塞对话（spec NFR）
- **Sources**: [Docling RAG 实战评测](https://pythondatabench.com/article/docling-python-parse-pdf-docx-html-rag-2026)、[文档解析方案大评测](https://juejin.cn/post/7605401415855767602)

## R6 实现补记：EPUB 引文定位链路（2026-10-01 实测）

定位功能首版"只到封面/不中不亮"连续踩坑，逐一定位根因后沉淀以下要点（改定位逻辑前先用无头复现验证）：

- **大小写**: Docling 输出的引文可能与原文大小写不一致（实测：chunk 引文 "Defining software architecture" vs 原文标题 "Defining Software Architecture"）→ 文本匹配与高亮范围搜索均须**大小写不敏感**
- **目录降权**: toc/nav 章节包含全部章节标题文本，会先于正文命中 → 命中目录类章节时**降权**（先记住、继续找正文，正文找不到才退回目录）
- **epubjs 四要点**（0.3.93 源码实测）:
  - 内存 archive（ArrayBuffer 载入）的章节加载**必须经 `book.load`**：`section.load(book.load.bind(book))`；不传则回退 fetch，拿到 SPA 兜底页面后静默匹配失败
  - XHTML 为 XML 解析模式，章节内容取根元素 `textContent`（无 `.body`）
  - 精确定位与高亮：`section.cfiFromRange(range)` 生成 CFI → `rendition.display(cfi)` 翻到引文页 + `annotations.highlight(cfi)` 高亮引文
  - 进度百分比依赖 `book.locations.generate()`（未生成位置索引时 epubjs 恒报 0%）
- **验证方法**: jsdom 无头复现真实 EPUB（逐章 `book.load` + `cfiFromRange` + CFI 对序列化文档做 `toRange` 校验），改前端定位逻辑前先跑通再交付

## R7 PDF 解析：文本层快通道（2026-10-01 事故复盘后重选型）

- **事故背景**: 《Game Engine Architecture》1240 页 PDF 用 Docling 全量 ML 解析时内存膨胀至 14.3GB，触发内核 OOM（杀掉 uvicorn 与 systemd，整台 WSL 崩溃）；匹配上游已知问题（docling-parse 跨页累积，700+ 页即触发，见 issue #3345）
- **Decision**: PDF 默认走**文本层快通道**（pypdfium2 直抽 + 启发式结构重建）；Docling 保留给 EPUB/DOCX 等（无 ML 布局模型、本身就快）并提供按需**深度解析**（分页批处理 120 页/批、默认关 OCR，约 20 分钟/1240 页、内存受控）
- **实测（1240 页 / 245 万字）**: 快通道解析 3.7s，含 embedding 全流程 **49s**；解析峰值内存 133MB（对照 Docling ~14GB）；产出 3046 chunks、195 个标题；断词（\\x02 连字符码位）/页眉页脚/目录条目/章节首行大字均已处理
- **代价（登记）**: 表格结构退化（内容可检索、结构丢失）；标题为字号启发式；复杂版面阅读顺序偶有瑕疵。缓解：表格占比检测（行内大列间隙，保守阈值 8% 页占比）→ parse_hint 提示"可深度解析"
- **选型对比**: pymupdf4llm（现成 markdown/标题，但 AGPL + 基准抽取准确率 69.86%）vs pypdfium2（Apache/BSD、基准 82.65%、需自建结构启发式）→ 选 pypdfium2
- **配套**: 解析批次间进度写 status_reason；启动扫尾把中断的 processing 文档标记"可重试"（不自动重跑，防崩溃连锁）
- **Sources**: [PDF parser benchmark](https://github.com/applied-artificial-intelligence/pdf-parser-benchmark/blob/main/docs/PARSERS.md)、[确定性文本抽取](https://quidproquo.cc/posts/ai/2026-08-06-pdf-text-extraction-libraries-en/)、[Docling OOM #3345](https://github.com/docling-project/docling/issues/3345)、[Docling 批量处理指南](https://mintlify.wiki/docling-project/docling/guides/batch-processing)、[Qiita 大 PDF 对策](https://qiita.com/henagineer/items/0ddd70cff12e368dad99)

## R8 备份：传输与加密选型（2026-10-01 决策）

- **Decision**: 本地备份先行（每日 pg_dump + 原文件镜像 + 保留策略 + 恢复脚本/演练，备份快照用**客户端加密**保护）；异地同步**延后至部署阶段**——rclone 仅作传输，上传的始终是客户端加密后的密文；厂商候选 OSS/COS（与服务器同厂同地域配套，换家仅改一行配置）
- **加密理由**: 服务端加密（SSE）的密钥在厂商手里——理论上厂商内部/依法调取可见明文，属于"信任转移"而非消除；客户端加密（零知识）使"选哪家"退化为价格/网络问题，隐私不依赖对任何厂商的信任（呼应 constitution IV 数据最小暴露）
- **代价（须知）**: 密钥/密码丢失 = 备份不可恢复（无找回）→ 密钥须离线多处保管；恢复演练必须覆盖解密链路
- **Alternatives**:
  - 厂商服务端加密（未采纳：信任转移而非消除）
  - Cloudflare R2 / Backblaze B2（免费额度优，但国内网络不稳；加密层兼容它，可随时切换）
  - 自建异地（NAS/低配 VPS 作 rclone 目标；运维成本高，留作将来备选）
- **本地阶段说明**: 本地无第三方，DB dump 仍做客户端加密（防介质泄密）；原文件镜像保持增量明文（与源数据同信任域，远程阶段由密文快照覆盖）
- **Sources**: [rclone crypt 零知识加密指南](https://rcloneview.com/support/zh-Hans/blog/encrypt-cloud-backups-crypt-remote-guide-rcloneview)、[OSS/COS 价格对比](https://www.net8.com.cn/article/129886.html)、[2026 对象存储深度评测](https://zhuanlan.zhihu.com/p/2071058527653729112)、[rclone 对象存储备份实战](https://www.zz1984.com/1080.html)

## R9 中文检索：pg_trgm 落地与压测（2026-10-02）

- **Decision**: 中文关键词检索用 **pg_trgm**（GIN 索引 + ILIKE 子串匹配）；不引入 zhparser——官方 pgvector 镜像无此扩展（需自编译自定义镜像），pg_trgm 1.6 内置可用（research「装包环境决定」落定）
- **实现**: `ix_chunks_content_trgm`（chunks.content gin_trgm_ops，迁移 `9d2b7c1e4f88`）；混合检索权重配置化（`retrieval_keyword_boost` / `retrieval_keyword_terms`，config.py）
- **压测记录**（本机 WSL，2026-10-02；10 万条合成 chunks / 表 640MB / trgm 索引 9.3MB；复跑：`server/tests/perf/pg_keyword_bench.sh`）:
  - ≥3 字中文模式（含不存在的词）：**0.06–0.37ms**（Bitmap Index Scan）
  - 真·最差：2 字短词且不匹配 → 全表扫描 **626ms**（LIKE 优化要求模式 ≥3 字符；626ms 仍低于 NFR P95≤2s）
  - 真实语料端到端：hybrid_search（含云 embedding 调用）**244–467ms**；SSE 检索+首字 **0.82s**（NFR：<10s，余量 12 倍）
- **边界与升级路径**: 更大规模下 2 字短词若超限 → 引入 zhparser（自建镜像）或 pg_bigm；检索接口不变（constitution VII 可替换）

## R10 对话搜索与侧栏收起（2026-10-02，用户要求）

- **Decision**: 对话搜索 = **消息正文子串 + 会话级结果 + 点击定位高亮**（不引入语义搜索；标题取自首问、正文命中已覆盖标题场景）。调研惯例支撑：仅搜标题、跳转进会话却不高亮均为反模式（AI UX Playground / ai-chat-outline）；侧栏收起 = 独立切换按钮 + localStorage 记忆 + Ctrl/Cmd+B + 首屏防闪跳（规避 localStorage×SSR 的可见跳变）。
- **实现**: `GET /api/conversations/search`（`conversations/router.py`）——ILIKE + pg_trgm GIN（新增索引迁移 `d51a9c73e2b4`，与 R9 同机制）；会话分组（首条命中 = 定位目标、命中数、按最近命中倒序）；命中扫描上限 500 防高频词全表拉取。共用 `app/textmatch.py`（like_pattern / make_snippet；资料列表 router 同步改用）。
- **前端**: 侧栏搜索框防抖 300ms、竞态"最新请求胜出"；结果行 = 标题 + 命中片段（高亮）+ N 处命中 + 时间；点击打开会话 → 滚动到 `#msg-{id}` 锚点 → 气泡短暂描边高亮；侧栏收起状态由 layout 内联脚本先于首屏应用（`html[data-sidebar]`）。
- **验证**: 真实库（16 会话 / 44 消息）实测：会话级结果 / 片段 / 排序 / 大小写不敏感正确；小表规划器选 Seq Scan（合理，44 行），`enable_seqscan=off` 确认谓词可走 `ix_messages_content_trgm`（Bitmap Index Scan）。

## R11 对话页视觉：对齐 ChatGPT 风格（2026-10-02，用户要求）

- **Decision**: 消息区改**平铺式**——助手回答去掉气泡边框、居中列（768px）文档式正文；用户消息 = 右侧浅灰圆角气泡（无边框）。依据（联网调研 ChatGPT 界面拆解）：ChatGPT 的核心特征即"助手无气泡 + 用户右侧灰气泡"的不对称布局，长回答（标题/列表/代码块）可读性显著优于双侧气泡；全灰阶体系（正文非纯黑、hover veil、细线边框、10px 圆角）。
- **实现**: 对话页局部（`globals.css` 对话页段 + `chat/page.tsx`）：用户气泡改中性灰（`--bubble-user-bg`，弃蓝调）；侧栏分层底色（`--sidebar-bg`）+ veil hover + 填充式 active；输入区改组合框（圆角容器内嵌圆形发送按钮 ↑，focus-within 描边，下方"回答可能有误，请以出处为准"小字）；空状态居中欢迎（文案定稿「向你的第二大脑提问吧」）+ 3 条示例问题（点击填入）；助手回答悬浮「复制」按钮（触屏常显）；流式输出文末闪烁光标；搜索跳转高亮从描边改为背景闪动（对无气泡正文同样可见）。资料/阅读/快照页不动。
- **明确不做**: 重新生成 / 停止生成 / 编辑消息（后端不支持）；助手头像。

## R12 对话引用 chip 点击失效修复（2026-10-02，真机反馈）

- **现象**: 回答里的引用编号 [N]（如"背包 DP"回答中的「[1]」）点击后"跳回对话页"而非出处（应指向快照/原文位置）。
- **根因**: react-markdown v9+ 默认 URL 消毒（`defaultUrlTransform`）只放行 `https?|ircs?|mailto|xmpp` 协议，自定义 `citation:` 被清成**空串** → chip 分支不命中，退化为 `<a href="">`；空 href 解析为当前页 URL，点击即"重开"当前对话页。
- **修复**: `renderAssistant` 传入自定义 `urlTransform`（放行 `citation:`，其余交默认消毒）+ `href` 为空时只渲染纯文本（防御其他被消毒链接）。用真实 react-markdown 渲染脚本验证：修复后 [N] 正确渲染为 `citation-chip` → `/snap/?id=…&from=chat`（网页来源）或 `/view/?…`（文件来源）。

## R13 MCP 接入（2026-10-02）

已迁移至独立 feature：**`specs/003-mcp-access/research.md`**（文档审计：MCP 作为新能力归档于 003）。

## R14 既往对话引用的来源追溯（2026-10-02，真机反馈驱动）

- **现象**: 「既往对话」来源的回答里，正文 [2][3] 点了没反应、[1] 指向对话文档本身的死胡同（`/view` 不支持 .conversation 格式）。
- **根因**: 回写文档只存"问/答"文本，且**回写只发生在模型兜底回答（FR-008）——这类回答本身没有 citations**；后续回答复制旧文本时携带了旧标记，前端把 [N] 按**本轮** citations 硬映射 → 误指/死标。
- **决策（联网调研）**: 引用应按稳定标识关联、点击回到原消息、不可达时优雅降级（[引用回复不能只存文本](https://developer.aliyun.com/article/1767603)、[TUIChat 引用定位](https://cloud.tencent.com/document/product/1047/60743?)）→ 采「**继承映射 + 回原对话 + 降级**」：无法追溯时 [N] 退为纯文本（绝不误指）。
- **实现**: `app/chat/inherit.py`（启发式：回写块定位原始消息 → 自带 citations 直接继承；复制型回答向前找"引用条数 ≥ 文本最大标记"的最近助手消息）；`enrich_citations` 生成时（orchestrator）与读取时（conversation_messages，**存量数据兜底**）共用；前端 [N] 用继承出处映射、「↩ 回到原对话」深链（`/chat/?conv=&msg=`，复用滚动+高亮）、「原对话出处：」列表。无 schema 变更（字段为计算附加值）。
- **验证**: 单测 +4；真实链路复现——原问题消息读取时即补全 `conversation_id/message_id/inherited_citations`（3 个原始 missav 网页出处）。

## R15 检索融合修正：关键词加成限定候选（2026-10-02，真机反馈驱动）

- **现象**: 「最近有没有看到什么适合我的upwork项目」未检索到已采集的 Upwork 项目条目（回答称"没有招聘项目记录"）。
- **测量归因**: 项目条目向量分 ~0.543 + 关键词加成 0.05 = **0.593，差 0.007 未过 0.6 命中线**；且现行关键词分支"文档名命中 → 该文档全部块匹配"时受 `LIMIT top_k` 影响，**只对无排序的任意子集加成**（54 块中约 6 块），同等相关块时有时无。对照实验：查询提纯不可靠（会把最相关条目挤出），未采纳。
- **决策（联网调研）**: 关键词加权应作用于融合候选集内、精确词（产品名/代号）适合关键词加成、候选池 ≈3×结果数（[DigitalOcean 混合检索](https://docs.digitalocean.com/products/vector-databases/opensearch/concepts/hybrid-search/)、RRF/加权融合实践）。
- **实现**: ① 关键词加成**只作用于向量候选**（`Chunk.id IN 候选`，不再独立召回——纯关键词块得分 ≤boost 远低于弱阈值，独立召回本就无实效）；② `retrieval_keyword_boost` 0.05→0.12；③ 向量候选池 `top_k×2 → ×3`。单测 59 全过（原"标题命中加成"测试语义保持）。
- **验证**: 目标查询实测——项目条目 0.593→**0.713/0.685 两条过线**；端到端问答从"没有招聘项目记录"变为**列出 2 个真实项目（Supabase $600 / Shopify Plus 时薪）并给出匹配度分析**。

## R15 补记：ASCII 关键词词边界修正（2026-10-02，F4 实现期验证发现）

- **现象**: F4 联网兜底 E2E 中，"Hugging Face 语音模型"查询被架构书强命中（0.6+）吞掉——定位为 `face` 按子串匹配命中 `interface`（架构书满篇 interface），假性加成把旁支内容顶过阈值。
- **修复**: ASCII 关键词改**词边界正则**（`\m…\M`，`~*`，re.escape 防元字符；仅作用于向量候选块 ≤18 行，无性能顾虑）；中文词保持 ILIKE 子串。单测：`face` 命中 "Face 工具"、不命中 "Interface 设计指南"。
- **遗留观察（F4 未决）**: 旁支性强命中仍可能先于联网（见 004 research 验证记录）。

### R15 补记二：人名分隔符弹性匹配（2026-10-02，用户实测驱动）

- **现象**: 用户「我是jasonL」问自己资料里的 profile，检索找不到（回答"没有找到 jasonL"），而库里明明有 "Jason L. - Full-Stack AI Developer …" 页面——原词边界正则 `\mjasonl\M` 无法命中 "Jason L."（空格/点分隔），页面仅剩向量 0.56 的弱命中。
- **修复**: ASCII 词项改为**词边界 + 词内弹性分隔**（`\mj[\s.\-–—_]*a…\M`）：连写/分写/连字符互通（jasonL ↔ Jason L. ↔ jason-l）；词边界保留（face↛interface、jasonL↛Jasper 均有单测）。
- **验证**: 「我是jasonL」「数据库里不是有jasonL的资料吗」「Jason L 的技术栈是什么」→ 全部强命中 profile 页、回答准确 ✓。

## R16 HNSW 召回退化与索引维护（2026-10-02 实测事故，验证驱动）

- **现象**: 验收题「康威定律」对应的书块在**精确扫描下排名第 1（cos 0.604）**，但索引扫描（默认 ef_search=40）**完全看不见它**——检索返回旁支垃圾当顶分，强命中丢失（用户可感知："明明库里有却答不上来"）；F4 验收多处 flake 的隐藏源头。
- **诊断路径**: Python 余弦 vs SQL 距离对照 → `enable_indexscan=off` 顺序扫描对照 → 升 `hnsw.ef_search`（40 丢 #1 → 1000 找回）→ `REINDEX` 后默认参数恢复。chunks 表高删改 churn（累计 n_tup_del 万级、dead_tup 数百）与 pgvector HNSW 依赖 VACUUM/REINDEX 修复图的机制吻合（[HNSW 维护实务](https://kingservers.com/blog/pgvector-hnsw-vacuum-reindex-rag/)、[索引生命周期与再索引](https://learn.microsoft.com/en-us/training/modules/implement-vector-search-azure-database-postgresql/4-manage-index-lifecycle-embedding-updates)）。
- **修复**: ① `retrieval_ef_search`（默认 200）对**全部**检索查询生效（`SET LOCAL hnsw.ef_search`，原仅时间过滤查询用 100）——召回余量兜底；② 维护流程：大量删除后 `REINDEX INDEX ix_chunks_embedding_hnsw` + `VACUUM chunks`（实测 14.6k 块约 1.5s）。
- **预防**: CLAUDE.md 运行备忘记录维护命令；"库里有的检索不到"类 flake 优先排查此项。

## R17 关键词加成的数字词项假性匹配（2026-10-02，验证驱动）

- **现象**: 「请计算 463718 乘以 37 …」被"智谱定价页"捕获的 SVG 坐标垃圾块强命中——查询词项 "37" 经词边界正则 `\m37\M` 命中坐标串 "37.8399"，+0.12 加成过线（该类数字密集垃圾块对数字查询本底分也偏高，实测原始 cos 0.60+）。
- **修复**: `_terms` 剔除**纯数字/符号词项**（词项须含中文或字母）；`GPT-4`、`time scale` 类混合词项不受影响。
- **测试**: `test_terms_drop_pure_numeric_tokens`（数字剔除 + 混合词保留）。
- **遗留观察（低优先）**: 浏览器采集的 SVG/CSS 类垃圾块（内联图形文本）对数字密集查询天然高分——候选缓解：网页分块阶段滤除高数字密度块；留待真实使用观察（004 research 有同类记录）。

## R18 回写自污染防护（2026-10-02，实测事故）

- **现象**: 模型「找不到 / 看不到你的资料」类**失败回答**被回写机制写入检索层后，成为同类问题检索的**最高分命中**（jasonL 查询被「没有找到 jasonL」的回答 0.73/0.81 顶置）——下一轮回答读到自己此前的失败记录，复读"找不到"，形成闭环误导。
- **修复**: 回写前过滤失败回答（`app/chat/writeback.is_no_info_answer`：找不到/没有找到/看不到你/无法确认你/没有访问你的 等标记，启发式+单测）；并清理已产生的 4 条自污染回写文档（2026-10-02）。
- **备注**: 与 004 FR-011 的措辞禁令互补——提示词从源头减少此类回答，守卫兜底防回写。
- **续（2026-10-02 实测补充）**: 标记表追加「看不到你 / 无法看到 / 没有关于你 / 没有您的」等实测变体（`test_writeback_guard` 同步扩充）。另：**入库管线与文档删除的竞态**（嵌入过程中文档被删 → `StaleDataError`）已做两层静默处理（2026-10-02，见 004 tasks T024）。
- **续二（2026-10-03 全量清理）**: 按用户指令"删除所有污染"全量复核回写文档（共 6 条）：删除 3 条失败/失实类（**编造浏览记录**「我昨天浏览了什么内容」——守卫无法用标记捕获的编造型；旧式失败短语「我没有你提供的【资料】」；含失实断言「你没有任何既往资料是关于你个人背景的」）；保留 3 条纯知识回答（SDD/久留美/missav 统计）。启示：**编造型回答需要内容级检测（守卫的标记式无法覆盖）**，候选缓解在回答端提示词（R20 已加固禁令）。
- **续三（2026-10-03 LLM 化，守卫标记词表整体退役）**: 15 条标记词表删除，改 `writeback.is_reusable_qa`——回写前 LLM 语义判定：失败说明 / **对用户个人数据的断言（含编造风险）** / 寒暄 → 不写回；可复用知识（含通用建议）→ 写回；判定失败保守跳过。判定在异步回写任务内执行（零请求延迟代价）。验证：真 LLM 探针 5/5（编造/失败/寒暄→否，知识/建议→是）；端到端（知识问答 writeback ok、寒暄零回写）；编造型自此可被捕获（标记词表时代不能）。

## R19 低置信多查询重试（FR-021，2026-10-02，用户实测驱动）

- **问题**: 用户多轮实测暴露「答案在库但检索不到」——不是索引/关键词缺陷（R15-R18 已修），而是**单一措辞、单次检索**的召回上限：中文问句 ↔ 英文资料（profile 页 0.53）、问法与文档措辞错位。关键洞察：改写者**不需要知道用户是谁**——通用的多措辞扇出即可补上表达差距。
- **实现前实测**: 「我的技术栈是什么」原样 0.53 → 单条改写 0.565（不够）→ 2-3 条多样变体「个人简介 开发经验 profile developer」→ **0.616 + 关键词加成 = 0.736 强命中**；「上次那本讲架构的书怎么说分层」0.604（可疑来源）→ 变体 0.797@Fundamentals（正解）。
- **实现**: `app/retrieval/rewrite.expand_queries`（≤3 条、同义/中英对照、失败返回空、去编号与回显）；orchestrator 仅在**无强命中**时触发（弱/库外路径），变体逐一检索后按 chunk 合并取最高分再判强/弱，触发与效果写 INFO 日志。成本：低置信查询 +1 次 LLM 调用（~1s）+ ≤3 次本地检索；强命中零开销。
- **风险与观测**: 扇出会放大假阳性面（变体可能把旁支内容推过线——「我常用的编程语言」变体命中 Game Engine 书 0.692，该例原查询已强命中、不触发）；验收题（拜占庭）变体实测 ≤0.518，无假强命中。「强命中但内容不对」（充分性判断）仍是独立未决项（见 004 research）。
- **备注（身份类问句的边界，2026-10-02 终版实测）**: 曾以「关于我」笔记兜底「我的技术栈是什么」（0.84 稳定命中）；**按用户决定撤销数据补丁后**复测：扇出对该类自我指涉问句**不可靠**（跨 7 次尝试救回约 1 次；补自我指涉变体规则后 0/5）——变体后 profile 页稳定落在 **0.49-0.59，恰在 0.6 命中线下**，仅偶然包含页面词汇（developer 等）的变体压线。结论：**身份类事实无法由检索侧保证**（ChatGPT 同构设计即用画像层做确定性注入）。**带名字的问法稳定**（「Jason L 的技术栈」经人名弹性加成命中 profile，2026-10-02 验证）。
- **备注（分块器）**: `chunk_markdown` 会把「标题行 + 列表」拆成碎片块（独立 6 字标题块与条目分家，致"技术栈是空的"误答）——笔记/卡片类内容须**段落自包含**；小碎片合并值得在分块器层面改进（遗留观察）。

## R20 浏览记录问句：清单意图覆盖与防编造（2026-10-03 实测事故）

- **现象**: 「我昨天浏览了什么内容」① 未走清单直达路径（第一遍答"没有资料，请再发一次"——要求用户重发）；② 用户重发后模型**编造浏览记录**（假的 PyTorch/HuggingFace 条目、错误日期 2025-06-06、example.com 假链接），且该编造回答被回写。
- **根因**: ① `_LIST_HINTS` 只覆盖「哪些/哪几/看过什么」等，**缺「浏览了什么」类句式** → 意图误判 search → 语义路径无强命中 → 兜底；② 系统提示词规则 2 只写了"不要声称没有浏览记录的访问权限"（有资料场景），**未禁止无资料时编造条目**——重发压力下模型脑补；③ 回写守卫缺「没有收到你/没有查到」变体，编造与失败回答双双漏过。
- **修复**: ① `_LIST_HINTS` 扩至「浏览了什么/看了什么/浏览过什么…」17 条（LLM 兜底提示同步）；② 规则 2 补「若本次没有提供网页资料，如实说明没有查到，严禁编造任何浏览条目、时间或链接」；③ 守卫标记补「没有收到/没有查到」。
- **验证**: 「我昨天浏览了什么内容」→ 清单直达：50 条真实记录、时间范围 2026-10-02~10-02、倒序、超限如实说明 ✓；单测 +6（意图 3 例 + 守卫变体 2 例等）。

## R21 查询规划器：取数方式交由 LLM 决定（FR-022，2026-10-03，用户驱动）

- **动因（用户批评）**: "每次出现问题只是在词表里加入一条"——句式规则路由（清单/语义意图词表连续两天被补两次、显式联网指令正则、回写守卫标记表补四次）是打地鼠；`_LIST_HINTS` 式分类永远追不全人类问法。
- **决策**: 学联网决策器先例，把"怎么取数"整体交给 LLM——单次工具调用规划（`app/chat/planner.py`）：`search_library(query, time_range?)` / `list_browsing(time_range)` / `web_search(query)`，最多 3 个、单轮不循环；执行器组装上下文（编号连续：本地 1..N + web N+1..），流式作答不变；**规划失败/未选择 → 回退默认检索基线**（安全网）。
- **一体化删除**: `_LIST_HINTS`/`_intent`/`TimeRange.intent`、清单 vs 语义分支、`_EXPLICIT_WEB_*` 正则、`websearch/planner.decide_search`（并入主规划器）——净减少四套脆断机制。
- **业界依据（联网调研）**: 自适应路由为 2026 主流；规划器用轻量模型（推理型规划 p50 恶化 2.4x）；硬上限+超时+失败回退基线；工具类型化契约（[CallSphere](https://callsphere.ai/blog/vw6g-agentic-rag-vs-traditional-rag-2026)、[Paiteq](https://www.paiteq.com/blog/agentic-rag/)、[TheRoadToEnterprise](https://theroadtoenterprise.com/blog/agentic-rag-vs-static-rag)、[MachineLearningMastery](https://machinelearningmastery.com/the-complete-guide-to-tool-selection-in-ai-agents/)）。
- **真机探针**: 浏览类→`list_browsing(昨天)` 3/3；联网指令→`web_search` 2/2；概念题（拜占庭/递归）→不联网 6/6；本地意图（"我的资料里的 React"）→不误判联网 ✓；裸指令/能力问句→不调用 ✓；康威题自动"语义×2 + 清单"并用 ✓。
- **时间词表退役（同日续）**: `_TEMPORAL_HINTS`/`looks_temporal` 一并删除——时间解析现仅由规划器的工具参数触发（planner 已断言"这是时间表达"），规则未命中一律 LLM 兜底；词表预检的历史使命（保护每条消息不盲调 LLM）已随路由退役而消失。
- **指代拼接改造（R21 续二，同日）**: `_retrieval_query`（≤20 字/指代词 → 无条件拼接上一轮问题作检索词）退役为 `_referential_splice`——**只作低置信重试的候选之一**。动因（用户查看该机制时当场暴露）：多轮会话中"短的新问题"被旧话题稀释——实测「游戏循环怎么实现」0.624 强命中，拼上无关"分层架构"后跌至 0.594 跌破阈值（可回答的问题因此掉入兜底）。改造后：强命中零拼接（真机 A 场景：回合 2 直接命中 Game Engine 书）；弱命中时拼接候选参与合并（B 场景验证：拼接查询把英文原文的康威段落到 0.562/rank1——但仍低于阈值、被旁支引言块挤占，属已记录的"旁支强命中/阈值边缘"类，机制本身生效）。
- **验收驱动精化（R21 续三·追记，同日）**: 全量验收追查暴露出对话窗口引入后的两个边界问题并修复：① **内容/清单边界**——「最近3天看过的网页里，X 是什么」被字面误判为清单意图（约 1/4 概率），走 `list_browsing` 只拿到条目元数据（标题/网址/时间）、没有正文，回答只能答"资料里没有该页面正文"；规则①明确：问某内容的含义/具体情况 → `search_library` + 时间限定，只有要"清单本身"才 `list_browsing`（工具描述同步注明材料性质）。② **历史不越权**——上一轮清单问答会把**自包含**的组合问句带偏（沿用上一轮工具选择）；规则⑥明确：历史仅服务于指代/省略消解，自包含问题按自身意图独立规划。修复后 sc007 组合问句循环 10/10 全绿；全量验收 11 通过 / 1 跳过 ✓。③ **断言口径**（002 侧，T051）：回答为聚合摘要（窗口 50 条时模型按站点归类概述、不逐条列名）→ sc007 原"标题逐字出现在回答中"断言约 1/4 概率失败（非检索故障）；改以**引用确定性**校验（citations 含近三天条目、不含窗口外条目）——材料来自数据库查询为确定性事实，回答措辞不是。
## 后续决策追加区（R22–R42，2026-10-03）

- **计费口径修正（R22，2026-10-03 审计二期）**: 审计发现旧计价（¥1.1/¥4.4，注释"deepseek-chat 空闲时段价"）与默认模型 `deepseek-flash` 错配、且无来源。联网核实官方定价页（[api-docs.deepseek.com/zh-cn/quick_start/pricing](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)，2026-10-03）：**deepseek-flash 输入未命中 空闲 ¥1 / 高峰 ¥2；输入命中 ¥0.02 / ¥0.04；输出 ¥4 / ¥8**（每百万 tokens）；高峰 = 北京时间周一至五 9-12、14-18（法定节假日未建模——按高峰计、略高估，已注释）。决策：`estimate_cost_cny` 改为**三档分价 + 峰谷倍率**（缓存命中/未命中分开计价——本就记录 `prompt_cache_hit_tokens`）；config 计价键替换为 hit/miss/output/倍率 四项。理由：金额为用户可见展示、须与官方口径一致；缓存命中价差 50×，单档计价会系统性高估。实施见 T062。
- **会话加固 / fail-closed / 写回策略（R23，2026-10-03 审计二期，用户「按推荐」批准）**: ① 会话（A1，[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) / [Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) 对照）：签名 SHA-1 → **SHA-256**；`users.session_epoch` + cookie 携带纪元——登出纪元 +1 → **无状态 cookie 的服务端吊销**（语义 = 全设备下线；A2 服务端会话表因单用户规模弃用，OWASP「登出须服务端失效」以纪元机制达成）；argon2 参数钉死 t=3 / m=64MiB / p=4（= RFC 9106 低内存档，原即库默认，改为显式不随库漂移）；登录对不存在用户跑 dummy 校验（防用户名枚举时序）。② fail-closed（B1）：SECRET_KEY / ADMIN_PASSWORD 哨兵默认值 → **启动即拒绝**（本地 .env 已配置、无影响）；cookie Secure 按环境自动（https 自动带，可显式强制）。③ 写回最小对齐（C1）：调研 mem0/Letta/Zep（[架构对比](https://dev.to/plur9/mem0-letta-and-plur-three-memory-architectures-three-different-bets-5dee)、[记忆整合实践](https://hindsight.vectorize.io/blog/2026/05/21/agent-memory-consolidation)）——业界共识 = 写时去重/冲突处理（recency-wins + 显式失效），衰减仅 Zep 类在做（mem0/Letta 均无）；落地**写前近似查重**（新问答 embedding 与 owner 全库最近邻相似度 ≥0.95 → 跳过回写，防重复问答污染检索）；**决策：保留每会话一文档 / 每轮一块 / 原文问答形态，不引入衰减与冲突处理**（单用户体量 + 原文保真优先，显式取舍）。实施见 T063/T064。
- **检索二段式重排（R24，2026-10-03 范式专项 A 方案，用户按推荐批准）**: 评测驱动（先建工具再决策）——`tests/acceptance/retrieval_eval.py`（20 题 × 5 方案：hit@6 / MRR / 分离间隔）。基线发现：① 召回无问题（各方案 hit@6=15/15）；真问题是**阈值的可分辨性**——纯向量正确块 0.51–0.76 vs 兜底题 top1 0.44–0.58 **分布重叠**（任何全局阈值分不干净，R19「0.49–0.59 贴线」的根）；② **+0.12 平铺加成在破坏判别**——兜底题靠"命中自身历史回写"（整句 ILIKE）被推过 0.60 强线（b02=0.70）；③ jieba 分词与现状于本集完全等价（无收益证据）；④ RRF 零收益且分数尺度（~0.016）与绝对阈值不兼容（业界共识：RRF 分不可对照相似度阈值，[Qdrant 调优](https://qdrant.tech/documentation/search-tuning/how-to-tune-hybrid-search/)、[实例 issue](https://github.com/27b-io/mcp-memory-service/issues/104)）。**决策：引入 cross-encoder 二段式重排**（retrieve→rerank 业界标准；[硅基流动 bge-reranker-v2-m3](https://siliconflow.cn/models?q=rerank)，与 embedding 同源 key、成本可忽略、延迟 +0.2~0.4s）。实测：正确块重排分 14/15 为 **0.77–0.998**、兜底题 top1 ≤ **0.377**——**分离间隔 +0.39**（旧口径为负）；**0.60/0.50 阈值恰落于间隔内、无需改值**（评分尺度随来源切换：重排成功=重排分，失败降级=余弦+加成）。落地：`hybrid_search` 候选池整体复评、失败静默降级（constitution VI）、`rerank_enabled` 可开关；单测覆盖替换/降级/禁用。T065。
  - 附记（分块，同批调研）: 业界研究（[chunking 系统分析](https://huggingface.co/papers/2601.14123)等）——**overlap 默认 0**（我们现状即 0，获背书）；常见最优 256–512 token（factoid）vs 我们 700–1200 字符——改动需全库重灌，列为独立决策待议。
- **界面中英切换（R25，2026-10-03 用户请求）**: 调研 Next.js 生态三选项（[next-intl vs react-i18next](https://www.locize.com/blog/next-intl-vs-next-i18next)、[next-intl 静态渲染须枚举 locale](https://dev.to/mukitaro/a-complete-guide-to-i18n-in-nextjs-15-app-router-with-next-intl-supporting-8-languages-1lgj)、[i18next 无路由客户端切换的 hydration 失败实例](https://stackoverflow.com/feeds/question/79789671)）：业界默认 next-intl 的范式是 **URL 路由前缀 + middleware**（静态导出须 `generateStaticParams` 枚举全部 locale）；react-i18next 无 RSC 优先支持、异步 `changeLanguage()` 在无路由方案下有已记录的 hydration 失败案例。本项目为 FastAPI 托管的**静态导出**、单用户、2 种语言，需求是**顶栏运行期切换**而非路由语言——既有深链契约（`/chat/`、`/view/?id=&page=&q=` 引用定位）不应改为 `/zh|/en/…`。**决策：自实现轻量 i18n**（Context + 双字典 + localStorage 记忆 + 浏览器语言默认；首帧固定中文与静态 HTML 一致、挂载后同步——规避 hydration 报警；zh/en 键编译期对齐防漏译）。零依赖、不动 URL。范围排除回答内容、后端错误消息、静态 metadata。实施见 T066。
- **日期控件替换（R26，2026-10-03 用户实测驱动）**: 中英切换后「清理浏览记录」日期输入仍显示「年/月/日」——查证（[Chrome 官方 FAQ](https://developer.chrome.google.cn/blog/quick-faqs-on-input-type-date-in-google-chrome?hl=zh-cn)、[W3C i18n 讨论](https://lists.w3.org/Archives/Public/public-i18n-archive/2024JulSep/0093.html)）：原生 `<input type="date">` 的显示格式由**浏览器/系统区域设置**决定，页面 `lang` 只是提示、实际被忽略，作者无标准手段控制（提交值恒为 yyyy-mm-dd、可用）。**决策（用户三选一选定）：引入业界组件 [react-day-picker](https://daypicker.dev)（v10）+ 自绘触发钮/弹层**——日历与格式跟随界面语言（官方 locale 机制，中文用 `locale/zh-CN`）；组件与 locale 数据经 `next/dynamic` 按需加载（仅首次打开弹层下载，页面首包 +1.5 kB）；value 契约不变（"YYYY-MM-DD"）。弃选：保留原生（英文界面下中文格式无法消除，Chrome 官方确认无接口）；纯文本输入（失去日历弹层）。实施见 T067。
- **防编造提示词对齐（R27，2026-10-03 三期 P1，事故驱动补规范对照）**: 对照 Anthropic《Reduce hallucinations》三条基础策略（[官方文档](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)：①允许"不知道" ②先引原文再作答 ③断言须有引用支撑）与《Cite your sources》范式：原提示已含"资料不足即明说 + [N] 标注"（策略①③雏形），缺"事实值不得臆测（数字/日期/人名）"与"编号必须真实存在、不得杜撰来源名"两条硬约束。落地：SYSTEM_PROMPT 规则 1 补三条（事实以原文为准 / 编号限本次实际提供 / 推断须标注）——2026-10-03 实测编造事故（虚构浏览条目）后的系统性对齐。实施见 T069。
- **SSE 客户端解析规范化（R28，2026-10-03 三期 P1）**: 手写 SSE 帧解析（`split("\n\n")` + 逐行前缀匹配）三处不规范：CRLF 不识别、多行 data 不按规范拼接、流中止无提示，且无取消、无读超时。业界共识（[fetch SSE 客户端模式](https://www.server-sent-events.com/frontend-consumption-client-patterns/fetch-based-sse-clients/)、[eventsource-parser 迁移记录](https://github.com/deepseek-ai/deepseek-harness/blob/master/.agents/notes/archived/simplification/2026-07-26-eventsource-parser-for-deepseek-sse.md)）：帧解析用 de-facto 标准库 [eventsource-parser](https://github.com/rexxars/eventsource-parser)（Vercel AI SDK / MCP SDK 同款、零依赖）；客户端配 AbortController 取消 + **静默看门狗**（业界明确「永远不要设总超时」——会掐断长回答/长流）。落地：手写解析退役；生成中发送钮变**停止**；60 秒无字节自动中止；断流未收 done 如实提示。实施见 T068。
- **SW 缓存策略分级（R29，2026-10-03 三期 P1）**: 原策略"静态一律缓存优先"未按资源类型分级。业界惯例（[SW 路由分类矩阵](https://github.com/VincentChuWaiChow/vanguard-frontier-agentic/blob/master/skills/frontend/service-worker-cache-strategy-review/references/route-classification-matrix.md)、[Workbox 教程](https://developers.google.com/codelabs/pwa-training/pwa03--working-with-workbox)）：内容哈希资源 CacheFirst（我们 `/_next/static/*` 现状即正确）；**未哈希静态 → StaleWhileRevalidate**（icons/manifest/字体，原地更新也能收敛）；HTML 导航不得缓存优先（"旧壳"反模式，我们现状正确）。落地：未哈希静态改 SWR，缓存版本 v2。实施见 T070。
- **备份加密参数与轮换（R30，2026-10-03 三期 P1）**: 现状 gpg 对称 AES-256 + 本机密钥文件。查证（[age vs GPG 备份讨论](https://security.stackexchange.com/posts/281772/revisions)、[单人管理员的密钥管理](http://www.bigiron.cc/guides/gpg-key-management-for-the-solo-admin-in-2026)）：自备份场景**对称加密是正确选择**；近期 gpg 对称模式自带完整性保护（MDC）；age 被称"现代默认"但换工具需重做密钥仪式与恢复链路、收益有限——**保留 gpg**。补强：S2K 参数显式固化（`--s2k-mode 3 --s2k-digest-algo SHA256`，防工具默认漂移——同 T063 argon2 显式化思路）；轮换策略（随事件：泄露/换机/满 1 年）+ 旧密钥保留期 + 演练节奏写入 README。实测：新参数备份 + restore drill 全量对照通过 ✓。实施见 T071。
- **内容指纹登记（R31，2026-10-03 三期 P1）**: `contentHash` 为 32 位 FNV-1a。对照（[RFC 9923（FNV）](http://mirror.turnkeylinux.org/ripe.net/rfc/authors/rfc9923.pdf)：FNV 适用非加密指纹场景、明确不适合需要抗碰撞的场景；[碰撞率分析](https://repositorio.bc.ufg.br/tedeserver/api/core/bitstreams/251c42bb-1b65-4752-82fc-80e80b2cfcfe/content)：32 位生日界约 7.7 万样本）：本场景 = **单 URL 单条对比**、10 分钟窗口、指纹表上限 500 条——单次误判概率 ≈2⁻³²，且方向为失败安全（最多漏一次重复采集）。simhash 面向**近似**去重，与"内容相同才跳过"的精确语义不匹配。**决策：保留 FNV-1a 32 位**；若未来扩为跨 URL 全量去重再升级 64 位。实施见 T072。
- **溯源写时留痕（R32，2026-10-03 三期 P1）**: 原机制 = 读取时文本匹配（全文 → 前 120 字前缀 + 扫描 50 条消息）回找源消息。数据血缘惯例 = **写时记录结构化来源、读时查表**而非内容匹配；且回写时源消息 id 本就已知。落地：回写时解析并存入 `chunks.provenance`（{message_id, citations}），读取零匹配取用；存量 6 块一次性回填；启发式仅保留为"无 provenance 旧数据"兜底。收益：前缀同文误配、>50 条会话漏配两类隐患对新数据整体消除。实施见 T073。
- **大文件上传登记（R33，2026-10-03 三期 P1）**: 200MB 上限整传。业界阈值口径（[Cloudflare Stream 可恢复上传](https://cloudflare-docs.cloudflare-docs.workers.dev/stream/uploading-videos/resumable-uploads/)）：>200MB 必须 tus；<200MB 可靠链路可直传、链路不可靠建议 tus。本项目现状 = 单用户、本机/局域网（可靠链路）、书/PDF 多为 <50MB——**维持整传**；**触发条件**：部署阶段（T035，WAN 场景）大文件上传成为常态时接入 tus（tuspyserver，FastAPI 现成组件）。实施见 T074。
- **跨语言检索调优：原问题常驻通道 + 重排短语敏感性发现（R34，2026-10-03 用户选定专项）**: 评测驱动（生产路径探针：规划器 → 多查询合并 → 阈值判定，逐题多轮）。诊断：① **g05（环境映射）**：原句重排 0.775，但规划器某轮改写词袋跌至 0.32——改写被当成**替换**而非叠加，偏离 MultiQuery 惯例（[LangChain MultiQueryRetriever](https://python.langchain.com/v0.2/docs/how_to/MultiQueryRetriever/)：原问题 "always kept, always first"；[参考实现](https://github.com/tkarim45/rag-architectures/blob/main/multi_query/README.md)：改写是增量召回通道）；② **g06（OpenAL 许可）**：正确块可被检索（向量 rank3、余弦 0.51）但重排分呈**短语抽奖**——同一块、同一问句族的近义短语稳定复现 0.06 ↔ 0.92（"OpenAL license 授权 音频库"=0.917，"OpenAL license 许可协议"=0.060，服务确定性已背靠背验证；完整问句 0.078–0.305）。**落地**：`_execute_plan` 合并循环新增**原问题常驻通道**（始终参与召回、时间范围沿用规划器首个时间窗；合并取 max，monotone-safe）——g05 锁稳（多次 3/3 与 6/6）；g06 通过轮 0.64–0.92（波动取决于抽奖）。规划器"紧凑短语"提示词改动经实测无增益，**已回退**（机制未证实前不加）。**新发现（已排期）**：③ 重排分短语脆弱性——R24 的阈值标定建立在该打分面上，其鲁棒性风险此前未知 → **立项 T076**（替代重排器对比评测，同题集 + 稳定性指标）；④ **扇出扩写的假强命中**——弱查询扩写变体可把无关页面推过强线（b02 实测：某轮变体让"猪八戒城市列表页"打到 0.712，与 R24 移除的平铺加成为同类问题的另一入口）→ **立项 T077**（T076 之后）；⑤ b04 假强命中=验收残留回写污染——**已清理**（2026-10-03，对话删除 API 级联；b04 top1 1.00→0.013 复核）。实施见 T075。
- **重排器换代：bge-reranker-v2-m3 → Qwen3-Reranker-4B（R35，2026-10-03 T076 评测驱动，用户选定）**: 新建 `tests/acceptance/rerank_eval.py`（**同一生产候选池**复评以隔离重排器变量 + 近义改写稳定性 + 延迟；报告落盘）。实测（20 题）：bge 分离 **−0.298**、改写抽奖跨度达 0.90（g05 0.036–0.94、g02 0.252–0.982——不止跨语言题，常规题同样抽奖）；**Qwen3-4B 分离 +0.643、全样本改写跨度 ≤0.21、正确分下限 0.787**；Qwen3-8B 分离 +0.812 但延迟 1.46s / 价格 2×；Qwen3-0.6B 判别力不足（兜底题打 0.967、分离 +0.028）淘汰。**决策**：切换 **Qwen3-Reranker-4B**（命中率同 15/15、判别余量充足、延迟 0.90s（+0.4s）、¥0.14/M——单用户成本可忽略）；**0.60/0.50 阈值沿用**（正确分下限 0.79+ 远高于 0.60、兜底上限 0.35 低于 0.50，无需复标定）。交叉参考：Qwen3 系多语言基准优于 bge（[Qwen3-Embedding 发布](https://qwen.ai/blog?id=qwen3-embedding)）；公开评测的否定题/中文口径警示（[negation 基准](https://daily.dev/posts/negation-in-rag-measured-most-rerankers-do-worse-than-a-coin-flip-jyhykvwrz)）未在本库题集复现。端到端：SC-002 hit_rate **1.0**（g06 修复；存留 b03/r02 为测试口径/状态漂移类，见 R34）。实施见 T076。
- **费用展示改全成本口径（R36，2026-10-03 用户需求）**: 原展示仅含回答模型 token 费，规划/扩检等 LLM 小调用、联网搜索、embedding/重排全部隐形。事实核查：智谱 Web Search **按调用次数**计费（[官方定价](https://docs.bigmodel.cn/cn/guide/start/pricing)：search_std ¥0.01/次、pro ¥0.03、sogou/quark ¥0.05；失败不计费）；bge-m3 @ 硅基流动 **免费**（¥0/M，2026-10 核实）；Qwen3-Reranker-4B ¥0.14/M（R35）；两家 API 均返回 usage（embedding=`usage.prompt_tokens`、rerank=`meta.tokens.input_tokens`——实测确认）。落地：ContextVar 单轮累加器（`app/costing.py`）——LLM 小调用经 complete_chat 自动计入（同一分档定价、含峰谷倍率）、联网按次（按引擎单价）、检索按 tokens；done 载荷与消息 usage 增 `cost_breakdown {llm, web, retrieval}`，**`cost_cny` 语义改为全成本合计**（历史消息为回答单调用口径——语义版本差异已注记）。实测：联网问题 `{llm 0.0033, web 0.01}`、库内问题 `{llm 0.0014, retrieval 0.0023}` ✓。不含：回写判定/回写 embedding 等发生在展示之后的异步后台成本。实施见 T079。
- **联网搜索质量：引擎换 sogou + 结果重排过滤（R37，2026-10-03 用户实测驱动）**: 诊断：规划器发出的查询本身优良（`Upwork most in-demand software project types 2025`），差在**引擎档位**——四组查询对照实测：search_std 与 search_pro **同源**（同查询结果完全一致）、均偏中文 SEO 内容农场（知乎/微信"新手必读"）；**search_pro_sogou 显著最优**（Upwork 官方招聘报告、rerank 对比文章、图灵奖获奖者直击、OpenAI 官网发布页），quark 次之（混合）。**决策（用户选定）**：① 默认引擎换 sogou（¥0.01→¥0.05/次，单用户可忽略；fallback 改 quark）；② 注入前加**结果重排过滤**（同"检索→重排"范式）：复用 cross-encoder 对「标题+摘要」按用户问题复评——阈值标定（同一批结果）：真相关 0.9+/部分相关 0.4–0.6/垃圾 ≤0.2 → `web_search_relevance_floor=0.3`；低于下限剔除、其余按分排序截断 top-N；**全部低相关 → 换备用引擎重试一次**（计入每日护栏）；重排失败/重排关闭 → 原序保留（静默降级）。实测（同题）：来源从"项目管理软件榜单"变为 5 条 Upwork 官方报告、回答引用真实增长数据并如实区分网络/通用知识；成本 `web 0.05 + 过滤重排费`。实施见 T081。
- **搜索+读页：多查询执行与正文提取（R38，2026-10-03 用户对比实测驱动）**: 用户对比发现与 DeepSeek（多次搜索+读 7 个页面）差距大，诊断出两处：① 规划器多条联网查询**只执行第一条**（成本约束），常把好的查询（如英文）丢掉；② 只消费搜索摘要、不读页面（004 原 Non-Goal）。业界范式（[Perplexity RAG 管线拆解](https://zhuanlan.zhihu.com/p/1969665049984480732)、[engineering-handbook 设计](https://raw.githubusercontent.com/handbook-academy/engineering-handbook/refs/heads/main/content/hld/part-8-case-studies/33-perplexity-ai-search.md)、[自托管 Perplexity clone](https://dev.to/kazkozdev/building-a-perplexity-clone-for-local-llms-in-50-lines-of-python-2p79)：查询扇出→语义预筛→**并行抓页→正文提取（trafilatura precision 模式，F1≈0.90）→段落级筛选**→带引用注入；抓取失败回退搜索摘要）。**决策（用户选定完整流水线）**：① `_build_web_context` 执行规划器**全部**联网查询（≤3），按 URL 合并去重后统一重排过滤；② 新模块 `app/websearch/reader.py`——并行抓取（并发 4/页超时 8s/字节上限 2MB/仅 text/html）、trafilatura precision 提取、**段落级重排筛选**（复用 cross-encoder，只注入最相关段落 ≤2000 字/页，失败→头部截断）、整体可关（`reader_max_pages=0`）；引用摘录改来自页面正文（失败回退摘要）。受控边界：单用户低频读少量公开页、不绕过反爬、不落盘（保留"不做整站爬取"）。实测（同题）：两条查询全执行（web ¥0.1）、回答引用 2026 官方技能报告具体数据（AI 集成 +178% 等）、引用摘录来自正文、全程 11s——与 DeepSeek 同级。实施见 T082。
- **联网检索全自建：SearXNG 自托管 + 免费加深（R39，2026-10-03 用户选型）**: 动因：用户对照成本（联网轮 ¥0.10，95%=搜索费）要求"**全部走自建、质量优先、可牺牲性能**"（另：抓 DeepSeek App 数据属 ToS 违规且不可维护，明确排除）。路径核查：[Brave 免费额度已终结](https://scavio.dev/blog/brave-search-api-killed-free-tier-what-now-2026)（2026 起须绑卡）；智谱资源包与按次同价（2000 次/100 元）；**自建 [SearXNG](https://github.com/searxng/searxng) = 零成本无限次**。落地：deploy/compose 增 searxng 服务（127.0.0.1:8888、JSON 开启、secret 经环境注入）；**实机网络裁剪引擎集**（`deploy/searxng/settings.yml`）——google/duckduckgo/brave/wikipedia 直连超时、baidu 验证码、quark 崩溃 → 保留 **sogou（质量最好）+ bing（base_url 换 cn.bing.com 后可用，关键修复）+ 360search**。架构：`web_search_provider` 默认 **searxng**（免费源 `paid=False`——不计每日护栏、成本恒 0）；**付费"升级"改为免费"加深"**——结果最好分 < `web_search_escalate_below`(0.45，标定数据) → 用既有扩写器改写查询变体二轮检索并合并（零成本，时间换质量）；智谱付费路径保留为 `web_search_paid_fallback` 开关（默认关）；读页上限 3→4。实测（Upwork 题）：**web 费用 ¥0**（原 ¥0.10）、总成本 ¥0.0046（≈20×降）、10s（与付费相当）；质量观察：免费引擎对此类查询返回平台介绍/知乎类页面（付费 sogou API 曾给出官方报告）——回答诚实呈现"没有排名数据"+ 通用知识补充；需要时开付费兜底开关即可回补该差距。实施见 T085。
- **DeepSeek 服务端搜索接入（R40，2026-10-03，用户驱动）**: 发现链：用户追问"DeepSeek App 用什么搜索 / 为什么 second-brain 接了 DeepSeek 却没有联网"→ 两段查证：① App 侧供应商为**博查**（[每经 2025-03 专访](http://m.nbd.com.cn/articles/2025-03-07/3779901.html)：爆火前已接入、春节"只选博查一家"；[21 财经](https://www.21jingji.com/article/20250523/herald/b28177c47722fba576acb7cba4f12a63.html)：承接国内 AI 应用 60% 联网请求）；② API 侧 DeepSeek 官方提供**服务端 web_search 工具**（`web_search_20250305`，挂 Anthropic 兼容端点，[LINUX DO 快讯](https://linux.do/t/topic/2252460/2)）——即用户在 Claude Code（`api.deepseek.com/anthropic`）里"感觉挺好用"的那个；second-brain 原链路（`/chat/completions` 纯补全、零工具声明）天然不具备（口径澄清：服务端工具是 Anthropic 兼容/Responses 式接口的概念，普通 chat 补全只有客户端函数调用）。真实 key 实测：`POST /anthropic/v1/messages` + Bearer（复用 `llm_api_key`，零新账号）→ `server_tool_use`→`web_search_tool_result` 块（title/url；正文密文**无明文摘要** → 重排按标题、正文由读页管线补）；模型自动中英改写查询（单调用 1-2 轮搜索）；**token 计费、无按次费**——单查询实测 ¥0.009–0.016（约博查零售 ¥0.036/次的 1/3）。**同题对比评测**（`tests/acceptance/websearch_provider_eval.py`，4 题）：SearXNG 0.2–0.4s/¥0，来源=门户/导航页（Upwork 题返回官网首页+注册页、美联储题返回主页+百科），**重排分却 0.92–0.99——闸门盲区再获实证（差距在索引层不在过滤层，"低分才升级"的兜底思路对 searxng 打底不成立）**；DeepSeek 3.1–3.6s/≈¥0.01，来源=Upwork 官方投资者报告与月度雇佣报告、央广网当期"美联储维持利率"新闻、专项分析——即此前羡慕的"DeepSeek 级"来源。**落地（T086）**：`app/websearch/deepseek.py`（`paid=True`：计每日护栏与 token 成本）；**默认源切至 deepseek（2026-10-03 用户确认）**——真机 E2E 验收 ✓（planning→web_search→generating；5 条 web 引用含 Upwork 官方新闻稿；`web ¥0.021`＞0 证明 token 计费路径生效）；searxng 保留为一行可切回的免费源。备选登记：博查直连（¥0.036/次，中文实测口碑最佳，未接）；Brave API（$5/千次 + 月 $5 免费额度，2026-02 起须绑卡；实测国内直连可达）；百度千帆（100 次/天免费，须实名）。实施见 T086。
- **网页引用「引文小窗」（R41，2026-10-03 用户实测驱动）**: 用户反馈：回答里 [1][2] 角标点击直接丢去系统浏览器，突兀。两条调研边界：① **iframe 直嵌原页被站点拒绝**——实测常引 10 来源半数不可嵌（upwork/github/baseten/staffingindustry ✗ XFO/CSP；cnr/nasdaq/zhihu/apifox/tryvibeworker 未见限制）；② **业界范式**（Perplexity/ChatGPT）= 悬停/点开「标题+域名+摘录」卡片 + 显式动作才开浏览器，无一家在应用内嵌原页（[Perplexity 交互拆解](https://wisechecker.com/how-to-view-sources-cited-in-perplexity-answer/)、[OpenAI Help](https://help.openai.com/en/articles/9237897-searching-the-web-with-chatgpt)、[iframe/CSP 限制解析](https://ai.engineer/talks/c-2eEv2ou7Y-why-mcp-chatgpt-apps-use-double-iframes)）。备选评估：截图小窗（无头 Chromium 整页截图，视觉=浏览器；重依赖 + 3–6s/页 + 强反爬站失败）、代理渲染（抓页去脚本重发；JS 站"空壳"风险）——均重。**决策（用户选定）**：小窗只放**回答所依据的原文摘录**（`citations.quote` ≤300 字，读页管线产物；无摘录时给提示）——零后端改动；浏览器访问由窗内「↗ 打开原文」显式触发；出处列表「↗ 打开网页」维持直开。实施见 T087。
- **模型迁移与思考档（R42，2026-10-03 用户驱动）**: 用户质疑"现在调用的 deepseek 是否不太聪明"→ 查证：app 实际跑 **`deepseek-chat`**（.env 覆盖了 config 默认的 flash）——**官方停用名单上的旧别名**（2026-07-24 曾计划下线，仍兼容响应，路由为 Flash 档非思考模式）；官方现役仅 **deepseek-flash（V4.1，284B/13B 激活）与 deepseek-v4-pro（1.6T）** 两档，均默认开思考、带 effort 档位（low/high/max，默认 high；`GET /models` 实证）。**迁移雷点（实测）**：V4 思维链占用 `max_tokens`——直接换模型名会把规划器（max_tokens=200）打空（实测正文为空）；关思考参数 `thinking:{"type":"disabled"}`（`thinking:false` 报 422）。**同题五档实测**（检索计划题）：关思考 1.4s/¥0.07分/泛；effort=low 9.5s/0.74分、high 6.4s/0.49分、max 10.8s/0.90分——**"开思考"是质量分水岭、档位间差异小（low 思考量甚至更多，单题噪声大）**；v4-pro@high 23.6s/~3.5分，与 flash 高档同级——**未值其 ~4× 价**（单题样本，非全场景结论）。**决策（用户选定）**：模型切 **deepseek-flash**；**分调用策略**——答案调用开思考（effort=high、`llm_answer_effort` 可配；思维链经 reasoning_content 流式转发、前端**折叠展示**：生成时展开实时刷新、出正文自动折叠为「已思考 Ns·点开查看」、仅当次可见不持久化），规划/扩检/时间解析与 `complete_with_tools` 工具调用**恒关思考**（防吃满小预算）；成本口径不变（思考计入 completion_tokens）。真机 E2E：thinking 事件 102 个/279 字流式透传、答案正确（96% 题）、总成本 ¥0.0054。实施见 T088。

- **词表终极退役：指代消解交给规划器（R21 续三，同日，用户驱动）**: 用户追问"ChatGPT/DeepSeek 怎么做的"→ 联网查证：**行业范式 = conversational query rewriting**（把最近对话喂给 LLM，将追问改写为自包含检索词——代词/省略/序数全靠模型原生消解，无任何词表；[实现范式](https://raw.githubusercontent.com/SumukhaK/agentic-rag/refs/heads/main/code-walkthrough/orchestration/rewrite.md)、[实践与坑](https://cloud.tencent.cn/developer/article/2402350)）。落地：`plan_retrieval` 携带**最近 3 轮对话窗口**+ 改写指令 → `_REFERENTIAL_HINTS` 词表与 `_referential_splice` **整体删除**（本项目最后一张句式词表）。真机探针 4/4：「书里怎么说的？」+游戏循环历史 → 「游戏循环 game loop 实现 书籍」（自包含+双语）；「那它想说明什么？」→「康威定律…」；「它的第三步…」→ SDD 第三步产出物（省略+序数消解）；无上下文 → 通用检索词不编造。端到端：B 场景翻盘——追问从"没有提到康威定律"变为**完整答出 Game Engine 书第 8 章游戏循环内容**。隐私：见 004 research R3 补记（同源接收方零新增暴露；FR-006 不变）。
- **垃圾块根治（R17 遗留观察闭环）**: 探针暴露"假强命中"——**56.2% 的块是浏览器采集页的内联 SVG 坐标/CSS 数字海**（"你叫什么名字"多次命中垃圾块 ≥0.6）。根治：① 入库侧语言字符比 < 0.5 的块不索引（`app/ingestion/quality.py`，单测覆盖）；② 存量清理**已执行**（用户授权，2026-10-03：删除 8493 块、总块 14829→6336、零残留，仅删 chunks、文档保留，REINDEX+VACUUM 按 R16 流程）。清理后复测：假强命中消失，残余的"名称"类命中为**语义重叠**（正文含「用户名称」字段），属正常检索行为（回答端已正确识破）。
- **验收联动**: sc003/sc004 的"库外题"三次被库内命中（句式误判→F4 语义→书内容真实覆盖+垃圾假命中）——清理后重选「光合作用」题（零语义钩子，4/4 稳定），全量验收 11 通过 / 1 跳过 ✓；经验：测试选题不得依赖"永远库外"，须按零钩子标准实测选取。

## 未决项（留给实现阶段）

- 云 embedding 默认提供商最终拍板（硅基流动 vs 百炼，凭实际测试效果）
- 异地对象存储厂商：部署阶段与服务器同厂选定（候选 OSS/COS；R8）
- 跨语言检索调优：SC-002 评测发现 2 例中文问/英文书查询未达命中阈值（环境映射、OpenAL 类）；候选：hit 阈值微调 / 查询双语扩展 / bge-m3 提示性改写（T040 记录）
- ~~中文 FTS 扩展选型~~ ✅ 已定：pg_trgm（2026-10-02，见 R9）
- 首个可用模型默认（DeepSeek，成本优先）在 .env 可切换
