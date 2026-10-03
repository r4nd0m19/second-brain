"""认证加固（审计二期 A1/B1）：会话纪元吊销、登出失效、fail-closed 配置检测。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import COOKIE_NAME, make_session
from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_SECRET_KEY, Settings
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
    # fail-closed（B1）：默认哨兵值 → 拒绝启动
    with pytest.raises(RuntimeError):
        Settings(secret_key=DEFAULT_SECRET_KEY).assert_secure()
    with pytest.raises(RuntimeError):
        Settings(admin_password=DEFAULT_ADMIN_PASSWORD).assert_secure()
    # 显式配置 → 通过
    Settings(secret_key="s3cret-value", admin_password="p4ss-value").assert_secure()
