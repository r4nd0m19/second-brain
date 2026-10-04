"""存储统计按账号隔离（T094）：计数与文件字节只反映当前用户；数据库大小为服务器维度。"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import COOKIE_NAME, make_session
from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Document, SourceType, User


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def client(engine, maker):
    async def _override_session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_storage_stats_scoped_to_owner(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    me = User(username=f"me-{uuid.uuid4().hex[:6]}", password_hash="x")
    other = User(username=f"other-{uuid.uuid4().hex[:6]}", password_hash="x")
    async with maker() as s:
        s.add_all([me, other])
        await s.flush()
        for owner, n in ((me, 2), (other, 3)):
            for i in range(n):
                s.add(
                    Document(
                        owner_user_id=owner.id,
                        name=f"d{i}",
                        format="md",
                        size_bytes=10,
                        sha256=uuid.uuid4().hex,
                        original_path="p",
                        source_type=SourceType.upload,
                    )
                )
        await s.commit()

    mine = tmp_path / str(me.id)
    mine.mkdir(parents=True)
    (mine / "a.bin").write_bytes(b"12345")
    others = tmp_path / str(other.id)
    others.mkdir(parents=True)
    (others / "b.bin").write_bytes(b"x" * 100)

    client.cookies.set(COOKIE_NAME, make_session(str(me.id), 0))
    r = await client.get("/api/stats/storage")
    assert r.status_code == 200
    data = r.json()
    assert data["documents"] == {"upload": 2}  # 只有我的文档计数
    assert data["storage_bytes"] == 5  # 只有我的目录字节
    assert data["storage_files"] == 1
