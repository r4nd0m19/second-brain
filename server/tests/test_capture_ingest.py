"""T009 契约测试：采集接收端点（contracts/capture-api.md 全分支）。

认证（缺 Bearer 401 / 无效 401 / 吊销 401 / scope 403）；行为（201 新建、200 幂等、
200 更新 reindexed、超限降级 skipped_oversize、413 天花板、429 限速、URL 规范化、回放头）。
"""

import gzip
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import COOKIE_NAME, make_session
from app.capture.security import generate_token
from app.config import settings
from app.db import get_session
from app.main import app
from app.models import CaptureToken, User

import app.capture.router as capture_router_module


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _html(body: str = "<h1>标题</h1><p>正文</p>") -> bytes:
    return body.encode()


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def account(maker):
    """独立用户 + 一枚有效凭据（每个测试独立限速额度）。"""
    async with maker() as s:
        user = User(username=f"cap-{uuid.uuid4().hex[:8]}", password_hash="x")
        s.add(user)
        await s.flush()
        plain, prefix, digest = generate_token()
        tok = CaptureToken(owner_user_id=user.id, name="pytest", prefix=prefix, token_hash=digest)
        s.add(tok)
        await s.commit()
        return {"user_id": str(user.id), "token": plain, "token_id": str(tok.id)}


@pytest_asyncio.fixture(loop_scope="session")
async def client(engine, monkeypatch):
    test_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with test_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    # 契约测试不跑后台入库（解析/embedding 不在本测试范围）
    monkeypatch.setattr(capture_router_module, "enqueue_ingestion", lambda *a, **k: None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── 认证 ──


async def test_missing_and_invalid_token_401(client):
    r = await client.post("/api/capture/pages", data={"url": "https://example.com/a"})
    assert r.status_code == 401
    r = await client.post(
        "/api/capture/pages", headers=_auth("sb_cap_nope"), data={"url": "https://example.com/a"}
    )
    assert r.status_code == 401


async def test_revoked_token_401(client, maker, account):
    async with maker() as s:
        tok = await s.get(CaptureToken, uuid.UUID(account["token_id"]))
        tok.revoked_at = datetime.now(timezone.utc)
        await s.commit()
    r = await client.get("/api/capture/ping", headers=_auth(account["token"]))
    assert r.status_code == 401


async def test_scope_mismatch_403(client, maker, account):
    async with maker() as s:
        plain, prefix, digest = generate_token()
        s.add(
            CaptureToken(
                owner_user_id=uuid.UUID(account["user_id"]),
                name="other",
                prefix=prefix,
                token_hash=digest,
                scope="other",
            )
        )
        await s.commit()
    r = await client.get("/api/capture/ping", headers=_auth(plain))
    assert r.status_code == 403


# ── 凭据管理（会话）+ ping ──


async def test_create_token_via_api_revoke_and_ping(client, account):
    client.cookies.set(COOKIE_NAME, make_session(account["user_id"]))
    r = await client.post("/api/capture/tokens", json={"name": "Windows Chrome"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["token"].startswith("sb_cap_")

    r = await client.get("/api/capture/ping", headers=_auth(created["token"]))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["scope"] == "capture"

    r = await client.get("/api/capture/tokens")
    assert r.status_code == 200
    assert len(r.json()) >= 2
    assert all("token_hash" not in item for item in r.json())

    # 吊销后立即失效（T015 DoD）
    r = await client.delete(f"/api/capture/tokens/{created['id']}")
    assert r.status_code == 204
    r = await client.get("/api/capture/ping", headers=_auth(created["token"]))
    assert r.status_code == 401

    # 彻底删除（2026-10-02）：仅限已吊销；删除后列表消失、再删 404
    r = await client.delete(f"/api/capture/tokens/{created['id']}", params={"purge": "1"})
    assert r.status_code == 204
    r = await client.get("/api/capture/tokens")
    assert all(item["id"] != created["id"] for item in r.json())
    r = await client.delete(f"/api/capture/tokens/{created['id']}", params={"purge": "1"})
    assert r.status_code == 404


async def test_purge_requires_revoked(client, account):
    """未吊销直接 purge → 409（先吊销后删除的两步语义）。"""
    client.cookies.set(COOKIE_NAME, make_session(account["user_id"]))
    created = (
        await client.post("/api/capture/tokens", json={"name": "待删除"})
    ).json()
    r = await client.delete(f"/api/capture/tokens/{created['id']}", params={"purge": "1"})
    assert r.status_code == 409
    assert "吊销" in r.json()["detail"]
    # 普通 DELETE 仍是吊销（非删除），凭据仍在列表中
    await client.delete(f"/api/capture/tokens/{created['id']}")
    listed = (await client.get("/api/capture/tokens")).json()
    assert any(item["id"] == created["id"] for item in listed)
    await client.delete(f"/api/capture/tokens/{created['id']}", params={"purge": "1"})


# ── 采集行为 ──


async def test_capture_create_update_idempotent_and_replay(client, account):
    h = _auth(account["token"])
    cap = str(uuid.uuid4())
    data = {
        "url": "https://example.com/post/1",
        "title": "示例文章",
        "text": "# 标题\n\n正文 A",
        "captured_at": "2026-10-02T08:00:00+00:00",
        "capture_id": cap,
    }
    r = await client.post(
        "/api/capture/pages", headers=h, data=data, files={"file": ("page.html", _html(), "text/html")}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    doc_id = body["id"]
    assert body["duplicate"] is False and body["snapshot"] == "kept"

    # 幂等：同 capture_id 重放 → 200 duplicate，不重复计数
    r2 = await client.post(
        "/api/capture/pages", headers=h, data=data, files={"file": ("page.html", _html(), "text/html")}
    )
    assert r2.status_code == 200 and r2.json()["duplicate"] is True

    # 同 URL 更新：带 fragment 的 URL → 规范化去 fragment；正文变化 → reindexed
    data2 = {
        **data,
        "url": "https://example.com/post/1#section",
        "text": "# 标题\n\n正文 B",
        "capture_id": str(uuid.uuid4()),
    }
    r3 = await client.post(
        "/api/capture/pages",
        headers=h,
        data=data2,
        files={"file": ("page.html", _html("<h1>B</h1>"), "text/html")},
    )
    assert r3.status_code == 200
    assert r3.json()["updated"] is True and r3.json()["reindexed"] is True

    # 列表（会话）可见浏览器来源；visit_count=2；URL 已规范化
    client.cookies.set(COOKIE_NAME, make_session(account["user_id"]))
    lst = await client.get("/api/documents", params={"source": "browser"})
    assert lst.status_code == 200
    entry = next(d for d in lst.json()["items"] if d["id"] == doc_id)
    assert entry["source_url"] == "https://example.com/post/1"
    assert entry["visit_count"] == 2
    assert entry["snapshot"]["state"] == "kept"

    # 快照回放：CSP sandbox + gzip 直出 + nosniff
    snap = await client.get(f"/api/documents/{doc_id}/snapshot")
    assert snap.status_code == 200
    assert "sandbox" in snap.headers["content-security-policy"]
    assert snap.headers["content-encoding"] == "gzip"
    assert snap.headers["x-content-type-options"] == "nosniff"
    # httpx 按 Content-Encoding 自动解压 → 能拿到明文即证明服务端 gzip 直出成立；
    # 内容是第二次上传的版本（同 URL 覆盖更新语义）
    assert "<h1>B</h1>" in snap.content.decode("utf-8")

    # 单条删除 → 快照不可达（404）
    d = await client.delete(f"/api/documents/{doc_id}")
    assert d.status_code == 204
    snap2 = await client.get(f"/api/documents/{doc_id}/snapshot")
    assert snap2.status_code == 404


async def test_oversize_snapshot_degrades(client, account, monkeypatch):
    monkeypatch.setattr(settings, "capture_max_snapshot_mb", 1)
    h = _auth(account["token"])
    big = b"<html>" + b"x" * 1_200_000 + b"</html>"
    r = await client.post(
        "/api/capture/pages",
        headers=h,
        data={"url": "https://example.com/big", "capture_id": str(uuid.uuid4())},
        files={"file": ("big.html", big, "text/html")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["snapshot"] == "skipped_oversize"
    client.cookies.set(COOKIE_NAME, make_session(account["user_id"]))
    await client.delete(f"/api/documents/{r.json()['id']}")


async def test_request_ceiling_413(client, account, monkeypatch):
    monkeypatch.setattr(settings, "capture_max_request_mb", 1)
    h = _auth(account["token"])
    big = b"x" * 1_500_000
    r = await client.post(
        "/api/capture/pages",
        headers=h,
        data={"url": "https://example.com/huge", "capture_id": str(uuid.uuid4())},
        files={"file": ("huge.html", big, "text/html")},
    )
    assert r.status_code == 413


async def test_rate_limit_429(client, account, monkeypatch):
    monkeypatch.setattr(settings, "capture_rate_limit", 2)
    h = _auth(account["token"])
    for _ in range(2):
        r = await client.post("/api/capture/pages", headers=h, data={"url": "ftp://bad"})
        assert r.status_code == 400
    r = await client.post("/api/capture/pages", headers=h, data={"url": "ftp://bad"})
    assert r.status_code == 429
    assert r.headers.get("retry-after")


async def test_empty_text_creates_metadata_only_entry(client, account):
    """正文提取失败（text 空串）→ 仅元信息条目（spec Edge Case），不再 400。"""
    h = _auth(account["token"])
    r = await client.post(
        "/api/capture/pages",
        headers=h,
        data={"url": "https://example.com/meta-only", "text": "", "capture_id": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["snapshot"] == "none"

    client.cookies.set(COOKIE_NAME, make_session(account["user_id"]))
    lst = await client.get("/api/documents", params={"source": "browser"})
    entry = next(d for d in lst.json()["items"] if d["id"] == body["id"])
    assert entry["status"] == "indexed"
    assert "仅元信息" in (entry["status_reason"] or "")
    await client.delete(f"/api/documents/{body['id']}")
