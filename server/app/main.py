"""second-brain 后端入口：API + 静态 PWA 托管（单进程，T012）。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth.middleware import ApiAuthMiddleware
from app.auth.router import router_auth, router_me
from app.auth.service import ensure_admin_user
from app.chat.router import router as chat_router
from app.conversations.router import router as conversations_router
from app.documents.router import router as documents_router
from app.ingestion.pipeline import mark_interrupted_documents

WEB_DIR = Path(__file__).resolve().parents[2] / "web" / "out"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_admin_user()  # 单用户初始化（T008）
    await mark_interrupted_documents()  # 上次中断的解析 → 标记可重试（R7）
    yield


app = FastAPI(title="second-brain", version="0.1.0", lifespan=lifespan)
app.add_middleware(ApiAuthMiddleware)
app.include_router(router_auth)
app.include_router(router_me)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(conversations_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── 静态 PWA 托管（存在构建产物时启用；/api 优先于回退路由）──
if WEB_DIR.exists():
    next_assets = WEB_DIR / "_next"
    if next_assets.exists():
        app.mount("/_next", StaticFiles(directory=next_assets), name="next-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = WEB_DIR / full_path
        if candidate.is_dir():  # 目录路由（如 /login/）→ 目录内 index.html
            candidate = candidate / "index.html"
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIR / "index.html")
