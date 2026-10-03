[English](README.md) | 中文

# second-brain · 个人第二大脑

> 浏览即入库、上传即入库的个人知识库：**采集 → 入库 → 检索问答 → 带出处回答**，单进程自托管，双端（Windows / Android）可用。

不是又一个聊天框——所有回答优先出自**你自己的资料与浏览记录**，每条结论附可点击的出处；
库外问题才交给模型兜底（可选联网），并把可复用的问答回写进库。

```text
┌─────────────┐   采集（阅读触发 + 快照）    ┌─────────────────┐
│ 浏览器扩展    │ ────────────────────────▶ │                 │
└─────────────┘                           │  FastAPI 单进程   │ ──▶ PostgreSQL + pgvector
┌─────────────┐   上传 PDF/EPUB/TXT/…     │  （API + PWA 托管）│       ├─ 向量 + 关键词 混合检索
│ PWA 双端     │ ◀────── 问答（SSE 流式）── │                 │       └─ cross-encoder 二段式重排
└─────────────┘                           └─────────────────┘
                                                  │
                                                  ├─▶ 云 LLM（deepseek-flash）· 云 Embedding（bge-m3）
                                                  ├─▶ Rerank（bge-reranker-v2-m3）· 联网搜索（智谱，可关）
```

## 能力总览

| 模块 | 能力 |
|------|------|
| **F1 核心问答** | 上传（PDF / EPUB / TXT / MD / DOCX）→ 解析分块 → 混合检索 → 带出处回答（正文 [N] 角标可跳原文）；模型兜底 + **LLM 判定的问答回写**（写前近似查重防重复） |
| **F2 浏览器采集** | 扩展按"阅读行为"自动采集（停留/滚动阈值）；单文件快照回放（CSP 沙箱隔离）；黑名单源头不采；断网排队重传 |
| **F3 MCP 接入** | 以 MCP（Streamable HTTP）把资料库接给 Claude Code 等 harness：检索 / 读文档 / 存笔记 |
| **F4 联网检索** | 库外问题可联网答题（智谱搜索，默认关闭、按日限次）；来源标注"来自网络"并附外链 |
| 阅读器 | EPUB 目录 / 页码（估算）/ 按页跳转 / 键盘翻页；PDF 内置预览；出处一键定位原文（PDF 页码 / 文本高亮 / EPUB CFI） |

检索链路的若干设计（评测驱动）：LLM 工具调用查询规划器（取代词表路由）、**二段式重排**（正确块分 0.77+ vs 噪声 ≤0.38，分离间隔 +0.39）、HNSW 维护流程、防编造回答守则——均留有调研与验收记录（见 `specs/`）。

## 技术栈

| 层 | 选型 |
|----|------|
| 服务端 | Python 3.12 · FastAPI · SQLAlchemy(async) · Alembic |
| 存储 | PostgreSQL 16 + pgvector（HNSW）· pg_trgm；原文件按归属落盘 |
| 检索 | 向量召回 + 关键词加成 → cross-encoder 重排（硅基流动 bge-reranker-v2-m3） |
| 模型 | 对话 deepseek-flash · Embedding BAAI/bge-m3 · 联网 智谱 Web Search（均可替换） |
| 前端 | Next.js 15（静态导出，由 FastAPI 同端口托管）· PWA 双端 |
| 采集 | Chrome MV3 扩展（esbuild + vitest） |
| 部署 | Docker（db）+ systemd + Caddy（见 `deploy/`）· 备份加密脚本 |

## 快速开始（本机）

前置：Python 3.12、Node ≥ 20、Docker、Chrome/Edge。

```bash
# 1. 数据库（pgvector，映射 127.0.0.1:5433）
docker compose -f deploy/docker-compose.yml up -d db

# 2. 环境变量（复制模板，填入真实值；ADMIN_PASSWORD / SECRET_KEY 必须改，
#    仍为默认值时服务会 fail-closed 拒绝启动）
cp .env.example server/.env

# 3. 服务端
cd server
uv venv && uv pip install -e ".[dev]"     # 或常规 venv + pip
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0     # 首次启动自动建管理员账号

# 4. 前端（静态导出到 web/out，由服务端同端口托管）
cd ../web && npm install && npm run build

# 5. 浏览器扩展（可选）
cd ../extension && npm install && npm run build   # 产物 dist/ → chrome://extensions 开发者模式加载
```

打开 `http://localhost:8000`，用 `.env` 里的 `ADMIN_USERNAME / ADMIN_PASSWORD` 登录。

## 测试与评测

```bash
# 单元测试（不依赖外部服务）
cd server && .venv/bin/pytest tests/ -q --ignore=tests/acceptance     # 117 项
cd extension && npm test                                              # 36 项

# 验收（需服务已启动；真实调用 LLM/Embedding）
cd server && .venv/bin/pytest tests/acceptance/ -q

# 质量评测（可重复、报告落盘）
.venv/bin/python tests/acceptance/sc002_eval.py       # 端到端答题：命中率/出处正确率
.venv/bin/python tests/acceptance/retrieval_eval.py   # 检索链对比：hit@6 / MRR / 分数分离间隔
```

## 目录结构

```text
server/     # FastAPI 服务端（app/ 业务 · tests/ 单测+验收+评测 · alembic/ 迁移）
web/        # Next.js 前端（静态导出，PWA）
extension/  # Chrome MV3 采集扩展
specs/      # ★ 项目文档（SDD）：每个 feature 的 spec / plan / tasks / research / contracts
deploy/     # 部署与备份（docker-compose / systemd / Caddy / 加密备份脚本）
.specify/   # spec-kit（SDD 工作流）配置、模板、项目档案（memory/project.md）
```

## 文档与工作流

本项目采用 **SDD（规格驱动开发）**：`specs/` 下的文档是事实源——需求在 `spec.md`，
决策与调研结论（含来源）在 `research.md`，实施与验收在 `tasks.md`，接口/数据模型各有契约。
代码变更必须对照同步文档（矩阵见 `.claude/CLAUDE.md`），工程纪律包括：

- **范式优先**：机制设计默认采用业界已验证方案，自研需举证（调研 → 征询 → 留痕）
- 开发在 feature 分支上进行（`001-core-qa` / `002-browser-capture` / `004-web-search`；`main` 始终为最新）
- 里程碑后跑一次 `/speckit-analyze` 兜底审计

## 安全基线

私有部署（数据不出自租服务器；仅检索命中片段发往模型 API）：密码 argon2id ·
签名会话 + **纪元吊销**（登出全设备失效）· 登录限速 · 采集 Bearer 令牌（服务端只存哈希）·
快照回放强制 CSP 沙箱 · 默认密钥 fail-closed 拒绝启动 · 备份加密（GPG AES-256）。

---

*私人项目 · 开发中（F1–F4 已可用，部署上线进行中）。详细状态见 `.specify/memory/project.md`。*
