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

## 未决项（留给实现阶段）

- 云 embedding 默认提供商最终拍板（硅基流动 vs 百炼，凭实际测试效果）
- 中文 FTS 扩展选型（zhparser vs pg_trgm，装包环境决定）
- 首个可用模型默认（DeepSeek，成本优先）在 .env 可切换
