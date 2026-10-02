"""对话全文搜索（2026-10-02）：会话级结果 / 定位目标 / 命中数 / 归属隔离 / 排序。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import COOKIE_NAME, make_session
from app.db import get_session
from app.main import app
from app.models import Conversation, Message, MessageRole, User


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def user(maker):
    async with maker() as s:
        u = User(username=f"conv-{uuid.uuid4().hex[:8]}", password_hash="x")
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
        c.cookies.set(COOKIE_NAME, make_session(str(user.id)))
        yield c
    app.dependency_overrides.clear()


def _at(days_ago: float = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _mk_conv(
    maker,
    user: User,
    title: str,
    msgs: list[tuple[MessageRole, str, datetime]],
) -> uuid.UUID:
    conv_id = uuid.uuid4()
    async with maker() as s:
        s.add(Conversation(id=conv_id, owner_user_id=user.id, title=title))
        for role, content, at in msgs:
            s.add(
                Message(
                    id=uuid.uuid4(),
                    owner_user_id=user.id,
                    conversation_id=conv_id,
                    role=role,
                    content=content,
                    created_at=at,
                )
            )
        await s.commit()
    return conv_id


async def test_search_message_body_and_snippet(client, maker, user):
    conv = await _mk_conv(
        maker,
        user,
        "部署问题",
        [
            (MessageRole.user, "铺垫文本" * 30 + "请问麒麟芯片的部署口令是什么？", _at(2)),
            (MessageRole.assistant, "口令是「星尘-42」。" + "说明" * 30, _at(2) + timedelta(minutes=1)),
        ],
    )
    await _mk_conv(maker, user, "无关会话", [(MessageRole.user, "今天天气不错", _at(1))])

    body = (await client.get("/api/conversations/search", params={"q": "麒麟芯片"})).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(conv)
    assert item["title"] == "部署问题"
    assert item["hit_count"] == 1
    assert item["hit"]["role"] == "user"
    assert "麒麟芯片" in item["hit"]["snippet"]


async def test_search_both_roles_count_and_first_hit_target(client, maker, user):
    await _mk_conv(
        maker,
        user,
        "双角色",
        [
            (MessageRole.user, "关于zzqk问题的提问", _at(3)),
            (MessageRole.assistant, "zzqk 的回答内容", _at(3) + timedelta(minutes=1)),
        ],
    )
    body = (await client.get("/api/conversations/search", params={"q": "zzqk"})).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["hit_count"] == 2
    assert item["hit"]["role"] == "user"  # 首条命中 = 打开后的定位目标
    assert "提问" in item["hit"]["snippet"]


async def test_search_owner_isolation(client, maker, user):
    async with maker() as s:
        other = User(username=f"conv-other-{uuid.uuid4().hex[:6]}", password_hash="x")
        s.add(other)
        await s.commit()
    await _mk_conv(maker, other, "别人的会话", [(MessageRole.user, "zzqk 在别人家", _at(1))])
    await _mk_conv(maker, user, "我的会话", [(MessageRole.user, "zzqk 在我家", _at(2))])

    body = (await client.get("/api/conversations/search", params={"q": "zzqk"})).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "我的会话"


async def test_search_ordering_recent_hit_first(client, maker, user):
    await _mk_conv(maker, user, "旧命中", [(MessageRole.user, "zzqk 旧", _at(5))])
    await _mk_conv(maker, user, "新命中", [(MessageRole.user, "zzqk 新", _at(0.5))])

    body = (await client.get("/api/conversations/search", params={"q": "zzqk"})).json()
    assert [i["title"] for i in body["items"]] == ["新命中", "旧命中"]


async def test_search_empty_q_and_case_insensitive(client, maker, user):
    empty = (await client.get("/api/conversations/search", params={"q": "  "})).json()
    assert empty == {"items": [], "total": 0}

    await _mk_conv(maker, user, "英文", [(MessageRole.user, "About HNSW Index", _at(1))])
    body = (await client.get("/api/conversations/search", params={"q": "hnsw"})).json()
    assert body["total"] == 1
    assert "HNSW" in body["items"][0]["hit"]["snippet"]
