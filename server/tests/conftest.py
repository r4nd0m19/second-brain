"""测试脚手架（T013）：独立测试库（自动建/清）+ 会话 fixture。"""

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base

TEST_DB = "secondbrain_test"


def _db_url(name: str) -> str:
    base = settings.database_url.rsplit("/", 1)[0]
    return f"{base}/{name}"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    # 确保测试库存在
    admin = create_async_engine(_db_url("postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    test_engine = create_async_engine(_db_url(TEST_DB))
    async with test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
