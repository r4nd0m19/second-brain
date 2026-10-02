"""MCP 服务端测试（2026-10-02）：凭据鉴权 / 协议握手 / 工具调用 / 写入权限门槛。

协议走真实 Streamable HTTP（ASGI 直连，json_response 模式）：
initialize → notifications/initialized → tools/list → tools/call。
"""

import hashlib
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.mcp.auth as mcp_auth_module
import app.mcp.server as mcp_server_module
import app.notes as notes_module
from app.capture.security import generate_token
from app.config import settings
from app.main import app
from app.mcp.server import mcp
from app.models import CaptureToken, Chunk, Document, DocumentStatus, SourceType, User
from app.retrieval import search as search_module


class _FakeStore:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def save(self, owner: str, doc: str, filename: str, fileobj):  # noqa: ANN001
        data = fileobj.read()
        self.saved[f"{owner}/{doc}/{filename}"] = data
        return f"{owner}/{doc}/{filename}", hashlib.sha256(data).hexdigest(), len(data)

    def delete_document_dir(self, owner: str, doc: str) -> None:  # noqa: ARG002
        pass


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def account(maker):
    """用户 + 三种 scope 的凭据各一枚（read/write/capture）。"""
    async with maker() as s:
        user = User(username=f"mcp-{uuid.uuid4().hex[:8]}", password_hash="x")
        s.add(user)
        await s.flush()
        tokens = {}
        for scope in ("read", "write", "capture"):
            plain, prefix, digest = generate_token()
            s.add(
                CaptureToken(
                    owner_user_id=user.id, name=f"pytest-{scope}", prefix=prefix,
                    token_hash=digest, scope=scope,
                )
            )
            tokens[scope] = plain
        await s.commit()
        return {"user_id": user.id, "tokens": tokens}


@pytest_asyncio.fixture(loop_scope="session")
async def fake_store():
    return _FakeStore()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mcp_running():
    """整个测试会话驱动一次 MCP 会话管理器（等价 prod lifespan）。

    约束：run() 每实例仅一次、且必须同任务进出（anyio cancel scope）——
    用专用后台任务承载 enter/exit；请求从其它任务 start_soon 是 SDK 设计允许的。
    """
    import asyncio

    stop = asyncio.Event()

    async def _serve() -> None:
        async with mcp.session_manager.run():
            await stop.wait()

    task = asyncio.get_running_loop().create_task(_serve())
    for _ in range(200):  # 等待 task group 就绪
        if mcp.session_manager._task_group is not None:
            break
        await asyncio.sleep(0.01)
    yield
    stop.set()
    await task


@pytest_asyncio.fixture(loop_scope="session")
async def client(engine, maker, monkeypatch, fake_store, mcp_running):
    # MCP 鉴权/工具层直接用 SessionLocal → 指向测试库
    monkeypatch.setattr(mcp_auth_module, "SessionLocal", maker)
    monkeypatch.setattr(mcp_server_module, "SessionLocal", maker)
    # 笔记写入：不落真实存储、不跑后台解析
    monkeypatch.setattr(notes_module, "get_blob_store", lambda: fake_store)
    monkeypatch.setattr(notes_module, "enqueue_ingestion", lambda *a, **k: None)
    # 检索层嵌入：假 provider（不调云 API）
    class _Embed:
        async def embed(self, texts, on_progress=None):  # noqa: ANN001, ANN201
            return [[1.0] * settings.embedding_dim for _ in texts]

    monkeypatch.setattr(search_module, "get_embedding_provider", lambda: _Embed())

    transport = ASGITransport(app=app)
    # base_url 取 localhost：过 DNS-rebinding Host 白名单（transport_security）
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c


def _headers(token: str | None, session_id: str | None = None) -> dict:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["mcp-session-id"] = session_id
    return headers


async def _rpc(client, method, params=None, *, token=None, session_id=None, req_id=1) -> dict:
    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
        headers=_headers(token, session_id),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _mcp_session(client, token: str) -> str:
    """initialize + initialized，返回 session id。"""
    resp = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        },
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    session_id = resp.headers.get("mcp-session-id")
    assert session_id
    note = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_headers(token, session_id),
    )
    assert note.status_code in (200, 202)
    return session_id


async def test_mcp_auth_requires_read_or_write(client, account):
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    # 无凭据 / 采集凭据（scope=capture）→ 401
    r1 = await client.post("/mcp", json=init_body, headers=_headers(None))
    assert r1.status_code == 401
    r2 = await client.post("/mcp", json=init_body, headers=_headers(account["tokens"]["capture"]))
    assert r2.status_code == 401
    # read 凭据 → 握手成功
    session_id = await _mcp_session(client, account["tokens"]["read"])
    assert session_id


async def test_mcp_tools_list_and_search(client, maker, account):
    async with maker() as s:
        doc = Document(
            id=uuid.uuid4(),
            owner_user_id=account["user_id"],
            name="MCP 测试资料",
            format="txt",
            size_bytes=10,
            sha256=uuid.uuid4().hex,
            status=DocumentStatus.indexed,
            source_type=SourceType.upload,
            original_path="",
        )
        s.add(doc)
        s.add(
            Chunk(
                id=uuid.uuid4(),
                owner_user_id=account["user_id"],
                document_id=doc.id,
                content="这是一段包含稀有词缀zzqk的正文",
                embedding=[1.0] * settings.embedding_dim,
            )
        )
        await s.commit()

    token = account["tokens"]["read"]
    session_id = await _mcp_session(client, token)

    tools = await _rpc(client, "tools/list", token=token, session_id=session_id)
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"search_knowledge", "get_document", "search_conversations", "save_note"} <= names

    hit = await _rpc(
        client,
        "tools/call",
        {"name": "search_knowledge", "arguments": {"query": "zzqk"}},
        token=token,
        session_id=session_id,
    )
    text = str(hit["result"])
    assert "zzqk" in text and "MCP 测试资料" in text
    assert hit["result"].get("isError") is not True


async def test_mcp_save_note_scope_gate_and_write(client, maker, account, fake_store):
    # 只读凭据调用 save_note → 拒绝（isError + 提示需要写入权限）
    read_session = await _mcp_session(client, account["tokens"]["read"])
    denied = await _rpc(
        client,
        "tools/call",
        {"name": "save_note", "arguments": {"title": "t", "content": "c"}},
        token=account["tokens"]["read"],
        session_id=read_session,
    )
    assert denied["result"].get("isError") is True
    assert "写入权限" in str(denied["result"])

    # write 凭据 → 写入成功：note 文档入库 + 内容落存储
    write_session = await _mcp_session(client, account["tokens"]["write"])
    ok = await _rpc(
        client,
        "tools/call",
        {"name": "save_note", "arguments": {"title": "来自 Claude Code 的笔记", "content": "结论：zzqk。"}},
        token=account["tokens"]["write"],
        session_id=write_session,
    )
    assert ok["result"].get("isError") is not True
    assert "processing" in str(ok["result"])  # {id, status} 已受理入库
    assert any("content.md" in key for key in fake_store.saved)

    async with maker() as s:
        from sqlalchemy import select

        doc = await s.scalar(
            select(Document).where(
                Document.owner_user_id == account["user_id"],
                Document.source_type == SourceType.note,
            )
        )
        assert doc is not None and doc.name == "来自 Claude Code 的笔记"


async def test_get_document_fallback_chunks(client, maker, account):
    """无原文件（回写类）→ 内容块拼接；含截断标记。"""
    from app.mcp import tools as tools_module

    async with maker() as s:
        doc = Document(
            id=uuid.uuid4(),
            owner_user_id=account["user_id"],
            name="回写文档",
            format="conversation",
            size_bytes=0,
            sha256=uuid.uuid4().hex,
            status=DocumentStatus.indexed,
            source_type=SourceType.conversation,
            original_path="",
        )
        s.add(doc)
        s.add(
            Chunk(
                id=uuid.uuid4(),
                owner_user_id=account["user_id"],
                document_id=doc.id,
                content="第一段",
                embedding=[0.0] * settings.embedding_dim,
            )
        )
        await s.commit()
        doc_id = doc.id

    async with maker() as s:
        result = await tools_module.get_document(s, account["user_id"], str(doc_id), max_chars=2)
    assert result["name"] == "回写文档"
    assert result["truncated"] is True
    assert result["content"] == "第一"

    # 不存在的 id → 明确报错
    async with maker() as s:
        try:
            await tools_module.get_document(s, account["user_id"], str(uuid.uuid4()))
            raise AssertionError("应抛 ToolError")
        except ToolError as exc:
            assert "不存在" in str(exc)
