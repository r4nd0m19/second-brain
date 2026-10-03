English | [中文](README.ch.md)

# second-brain · Your Personal Second Brain

> A self-hosted personal knowledge base where browsing and uploads flow straight in:
> **capture → ingest → retrieval Q&A → answers with citations**. Single process, usable on Windows / Android.

Not another chat box — answers come first from **your own documents and browsing history**,
every claim carries a clickable citation; only out-of-corpus questions fall back to the model
(optionally with web search), and reusable Q&As are written back into the library.

```text
┌─────────────┐   capture (reading-triggered + snapshot)   ┌─────────────────┐
│ Browser ext. │ ─────────────────────────────────────────▶ │                 │
└─────────────┘                                            │  FastAPI (single │ ──▶ PostgreSQL + pgvector
┌─────────────┐   upload PDF/EPUB/TXT/…                    │  process: API +  │       ├─ vector + keyword hybrid retrieval
│ PWA (2 ends) │ ◀──────────── streaming Q&A (SSE) ──────── │  PWA hosting)    │       └─ cross-encoder two-stage rerank
└─────────────┘                                            └─────────────────┘
                                                                   │
                                                                   ├─▶ Cloud LLM (deepseek-flash) · Cloud Embedding (bge-m3)
                                                                   ├─▶ Rerank (bge-reranker-v2-m3) · Web search (Zhipu, optional)
```

## Capabilities

| Area | What it does |
|------|--------------|
| **F1 Core Q&A** | Upload (PDF / EPUB / TXT / MD / DOCX) → parse & chunk → hybrid retrieval → cited answers (inline `[N]` markers jump to the source); model fallback + **LLM-judged Q&A writeback** (with a near-duplicate pre-check) |
| **F2 Browser capture** | Extension auto-captures on reading behavior (dwell time / scroll depth); single-file snapshot replay (CSP-sandboxed); blocklisted sites never captured at the source; offline queue with retry |
| **F3 MCP access** | Exposes the library to Claude Code and other harnesses via MCP (Streamable HTTP): search / read document / save note |
| **F4 Web search** | Web-grounded answers for out-of-corpus questions (Zhipu search; off by default, daily-capped); sources labeled "from the web" with external links |
| Reader | EPUB table of contents / page numbers (estimated) / jump-to-page / keyboard paging; built-in PDF preview; one-click source location (PDF page / text highlight / EPUB CFI) |

Retrieval-pipeline design (eval-driven): LLM tool-calling query planner (replacing wordlists),
**two-stage reranking** (correct chunks score 0.77+ vs. noise ≤ 0.38, separation margin +0.39),
HNSW maintenance routine, anti-fabrication answer rules — all backed by research and acceptance records (see `specs/`).

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12 · FastAPI · SQLAlchemy (async) · Alembic |
| Storage | PostgreSQL 16 + pgvector (HNSW) · pg_trgm; original files on disk, per-owner |
| Retrieval | Vector recall + keyword boost → cross-encoder rerank (SiliconFlow bge-reranker-v2-m3) |
| Models | Chat: deepseek-flash · Embedding: BAAI/bge-m3 · Web search: Zhipu (all swappable) |
| Frontend | Next.js 15 (static export, served by FastAPI on the same port) · PWA for both ends |
| Capture | Chrome MV3 extension (esbuild + vitest) |
| Deployment | Docker (db) + systemd + Caddy (see `deploy/`) · encrypted backup scripts |

## Quick start (local)

Prerequisites: Python 3.12, Node ≥ 20, Docker, Chrome/Edge.

```bash
# 1. Database (pgvector, bound to 127.0.0.1:5433)
docker compose -f deploy/docker-compose.yml up -d db

# 2. Environment (copy the template and fill in real values; ADMIN_PASSWORD / SECRET_KEY
#    are required — the server refuses to boot (fail-closed) while they hold default values)
cp .env.example server/.env

# 3. Server
cd server
uv venv && uv pip install -e ".[dev]"     # or a plain venv + pip
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000 --host 0.0.0.0     # first boot creates the admin account

# 4. Frontend (static export to web/out, served by the server on the same port)
cd ../web && npm install && npm run build

# 5. Browser extension (optional)
cd ../extension && npm install && npm run build   # dist/ → load unpacked at chrome://extensions
```

Open `http://localhost:8000` and log in with `ADMIN_USERNAME / ADMIN_PASSWORD` from `.env`.

## Tests & evals

```bash
# Unit tests (no external services required)
cd server && .venv/bin/pytest tests/ -q --ignore=tests/acceptance     # 117 tests
cd extension && npm test                                              # 36 tests

# Acceptance (server must be running; calls real LLM/Embedding APIs)
cd server && .venv/bin/pytest tests/acceptance/ -q

# Quality evals (repeatable, reports written to disk)
.venv/bin/python tests/acceptance/sc002_eval.py       # end-to-end Q&A: hit rate / citation accuracy
.venv/bin/python tests/acceptance/retrieval_eval.py   # retrieval comparison: hit@6 / MRR / score separation
```

## Repository layout

```text
server/     # FastAPI backend (app/ business logic · tests/ unit+acceptance+eval · alembic/ migrations)
web/        # Next.js frontend (static export, PWA)
extension/  # Chrome MV3 capture extension
specs/      # ★ Project documentation (SDD): spec / plan / tasks / research / contracts per feature
deploy/     # Deployment & backup (docker-compose / systemd / Caddy / encrypted backup scripts)
.specify/   # spec-kit (SDD workflow) config, templates, project charter (memory/project.md)
```

## Docs & workflow

This project follows **SDD (spec-driven development)**: the documents under `specs/` are the
source of truth — requirements in `spec.md`, decisions and research (with sources) in
`research.md`, implementation and acceptance in `tasks.md`, interfaces and data models in
dedicated contracts. Code changes must keep documents in sync (matrix in `.claude/CLAUDE.md`).
Engineering discipline includes:

- **Paradigm-first**: mechanism design defaults to industry-proven approaches; anything
  home-grown must be justified (research → consult → record)
- Development happens on feature branches (`001-core-qa` / `002-browser-capture` /
  `004-web-search`; `main` is always current)
- A `/speckit-analyze` audit after each milestone

## Security baseline

Private deployment (data stays on your own server; only retrieved snippets go to model APIs):
argon2id passwords · signed sessions with **epoch revocation** (logout invalidates all devices) ·
login rate limiting · capture bearer tokens (the server stores hashes only) · snapshot replay
forced into a CSP sandbox · fail-closed boot while default secrets are in place · encrypted
backups (GPG AES-256).

---

*Private project · in development (F1–F4 usable; production rollout in progress).
Detailed status in `.specify/memory/project.md`.*
