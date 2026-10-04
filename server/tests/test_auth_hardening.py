"""认证加固（审计二期 A1/B1）：会话纪元吊销、登出失效、fail-closed 配置检测。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import ratelimit
from app.auth.security import COOKIE_NAME, hash_password, make_session
from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_SECRET_KEY, Settings, settings
from app.db import get_session
from app.main import app
from app.models import User


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def user(maker):
    async with maker() as s:
        u = User(username=f"auth-{uuid.uuid4().hex[:8]}", password_hash="x")
        s.add(u)
        await s.commit()
        return u


@pytest_asyncio.fixture(loop_scope="session")
async def client(engine, user):
    test_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with test_maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_epoch_match_ok(client, user):
    client.cookies.set(COOKIE_NAME, make_session(str(user.id), 0))
    assert (await client.get("/api/me")).status_code == 200


async def test_epoch_mismatch_rejected(client, user):
    # 纪元不匹配 = 服务端已吊销（如其他设备登出触发全设备下线）
    client.cookies.set(COOKIE_NAME, make_session(str(user.id), 7))
    assert (await client.get("/api/me")).status_code == 401


async def test_logout_bumps_epoch_and_invalidates_old_cookie(client, user, maker):
    old = make_session(str(user.id), 0)
    client.cookies.set(COOKIE_NAME, old)
    assert (await client.get("/api/me")).status_code == 200

    assert (await client.post("/api/auth/logout")).status_code == 204

    # 旧 cookie（纪元 0）立即失效
    client.cookies.set(COOKIE_NAME, old)
    assert (await client.get("/api/me")).status_code == 401
    # 数据库纪元已 +1
    async with maker() as s:
        refreshed = await s.get(User, user.id)
        assert refreshed is not None and refreshed.session_epoch == 1


def test_default_config_refuses_boot():
    # fail-closed（B1；T093 强化）：默认哨兵值 / 空值 / 过弱值 → 拒绝启动
    with pytest.raises(RuntimeError):
        Settings(secret_key=DEFAULT_SECRET_KEY).assert_secure()
    with pytest.raises(RuntimeError):
        Settings(admin_password=DEFAULT_ADMIN_PASSWORD).assert_secure()
    with pytest.raises(RuntimeError):  # T093：空值不再静默通过（注释掉值的常见误配）
        Settings(secret_key="").assert_secure()
    with pytest.raises(RuntimeError):
        Settings(secret_key="x" * 31).assert_secure()
    with pytest.raises(RuntimeError):
        Settings(admin_password="").assert_secure()
    with pytest.raises(RuntimeError):
        Settings(admin_password="1234567").assert_secure()
    # 显式配置（长度合规）→ 通过
    Settings(secret_key="s" * 32, admin_password="p4ss-word").assert_secure()


# ── T093：登录面加固（IP 级限速 / schema 长度上限）──


@pytest.fixture(autouse=True)
def _clean_ratelimit():
    ratelimit.reset_state()
    yield
    ratelimit.reset_state()


async def test_login_ip_rate_limit_blocks_random_usernames(client, monkeypatch):
    """随机用户名绕过：单账号键永不触发，但 IP 键必须拦下（第 4 次 429）。"""
    monkeypatch.setattr(settings, "login_rate_limit", 100)
    monkeypatch.setattr(settings, "login_rate_limit_ip", 3)
    for _ in range(3):
        r = await client.post(
            "/api/auth/login",
            json={"username": f"nobody-{uuid.uuid4().hex[:8]}", "password": "x"},
        )
        assert r.status_code == 401
    r = await client.post(
        "/api/auth/login", json={"username": f"nobody-{uuid.uuid4().hex[:8]}", "password": "x"}
    )
    assert r.status_code == 429  # 全新用户名，但同 IP 第 4 次 → 拦


async def test_login_user_key_rate_limit_still_works(client, monkeypatch):
    """单账号键行为不变：同用户名第 3 次失败 → 429。"""
    monkeypatch.setattr(settings, "login_rate_limit", 2)
    monkeypatch.setattr(settings, "login_rate_limit_ip", 100)
    body = {"username": "me-typo-test", "password": "x"}
    assert (await client.post("/api/auth/login", json=body)).status_code == 401
    assert (await client.post("/api/auth/login", json=body)).status_code == 401
    assert (await client.post("/api/auth/login", json=body)).status_code == 429


async def test_login_success_clears_both_keys(client, monkeypatch, maker):
    """登录成功清空单账号键与 IP 键——正常用户不被历史失败拖累。"""
    monkeypatch.setattr(settings, "login_rate_limit", 3)
    monkeypatch.setattr(settings, "login_rate_limit_ip", 3)
    name = f"login-{uuid.uuid4().hex[:8]}"
    async with maker() as s:
        s.add(User(username=name, password_hash=hash_password("good-pass-123")))
        await s.commit()

    for _ in range(2):
        assert (
            await client.post("/api/auth/login", json={"username": name, "password": "wrong"})
        ).status_code == 401
    assert (
        await client.post("/api/auth/login", json={"username": name, "password": "good-pass-123"})
    ).status_code == 204
    # 若两键未清空：单账号键已 2 次 + 本次 = 3 → 会被 429；能拿到 401 即证明已清空
    assert (
        await client.post("/api/auth/login", json={"username": name, "password": "wrong"})
    ).status_code == 401


async def test_login_schema_length_limits(client):
    """超长用户名/密码 → 422（防限速器键膨胀与 argon2 开销放大）。"""
    assert (
        await client.post("/api/auth/login", json={"username": "u" * 65, "password": "x"})
    ).status_code == 422
    assert (
        await client.post("/api/auth/login", json={"username": "u", "password": "p" * 257})
    ).status_code == 422


def test_api_docs_disabled_by_default():
    """T093：/docs /redoc /openapi.json 默认关闭（未认证的 API 结构暴露面）。"""
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
