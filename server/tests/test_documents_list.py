"""列表增强（2026-10-02）：分页 / 搜索（标题·站点·网址·正文）/ 排序 契约测试。

覆盖：分页信封与钳制、排序白名单与方向、搜索范围与 match 标记、正文片段、
LIKE 通配符转义（用户输入按字面量匹配）、非法 sort 400。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import COOKIE_NAME, make_session
from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Chunk, Document, DocumentStatus, SourceType, User


@pytest_asyncio.fixture(loop_scope="session")
async def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def user(maker):
    async with maker() as s:
        u = User(username=f"list-{uuid.uuid4().hex[:8]}", password_hash="x")
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


async def _mk_doc(
    maker,
    user,
    name: str,
    *,
    source: SourceType = SourceType.upload,
    size: int = 1000,
    site_name: str | None = None,
    source_url: str | None = None,
    visit_count: int | None = None,
    last_captured_at: datetime | None = None,
    chunks: list[str] | None = None,
) -> str:
    doc_id = uuid.uuid4()
    async with maker() as s:
        doc = Document(
            id=doc_id,
            owner_user_id=user.id,
            name=name,
            format="txt",
            size_bytes=size,
            sha256=uuid.uuid4().hex,
            status=DocumentStatus.indexed,
            source_type=source,
            original_path="test",
            site_name=site_name,
            source_url=source_url,
            visit_count=visit_count,
            last_captured_at=last_captured_at,
        )
        s.add(doc)
        for content in chunks or []:
            s.add(
                Chunk(
                    id=uuid.uuid4(),
                    owner_user_id=user.id,
                    document_id=doc_id,
                    content=content,
                    embedding=[0.0] * settings.embedding_dim,
                )
            )
        await s.commit()
    return str(doc_id)


async def test_pagination_envelope_and_clamping(client, maker, user):
    for i in range(25):
        await _mk_doc(maker, user, f"分页书-{i:02d}")

    r = await client.get("/api/documents", params={"page_size": 20})
    body = r.json()
    assert r.status_code == 200
    assert body["total"] == 25 and body["page"] == 1 and body["page_size"] == 20
    assert len(body["items"]) == 20

    r2 = await client.get("/api/documents", params={"page": 2, "page_size": 20})
    assert len(r2.json()["items"]) == 5

    # 越界页钳制到最后一页；page_size 超上限钳制到 100
    r3 = await client.get("/api/documents", params={"page": 99, "page_size": 20})
    assert r3.json()["page"] == 2 and len(r3.json()["items"]) == 5
    r4 = await client.get("/api/documents", params={"page_size": 100000})
    assert r4.json()["page_size"] == 100


async def test_sort_whitelist_and_direction(client, maker, user):
    await _mk_doc(maker, user, "B-书", size=300)
    await _mk_doc(maker, user, "A-书", size=100)
    await _mk_doc(maker, user, "C-书", size=200)

    asc = (await client.get("/api/documents", params={"sort": "name"})).json()["items"]
    assert [d["name"] for d in asc] == ["A-书", "B-书", "C-书"]
    desc = (await client.get("/api/documents", params={"sort": "-size"})).json()["items"]
    assert [d["name"] for d in desc] == ["B-书", "C-书", "A-书"]

    bad = await client.get("/api/documents", params={"sort": "drop_table"})
    assert bad.status_code == 400
    assert "sort" in bad.json()["detail"]


async def test_search_name_and_like_escape(client, maker, user):
    await _mk_doc(maker, user, "架构整洁之道")
    await _mk_doc(maker, user, "折扣 100% 特辑")
    await _mk_doc(maker, user, "折扣 100X 特辑")

    hit = (await client.get("/api/documents", params={"q": "架构"})).json()
    assert hit["total"] == 1
    assert hit["items"][0]["match"]["type"] == "name"

    # "%" 是字面量而非通配符：只命中含 "100%" 的那条
    literal = (await client.get("/api/documents", params={"q": "100%"})).json()
    assert literal["total"] == 1
    assert literal["items"][0]["name"] == "折扣 100% 特辑"

    none = (await client.get("/api/documents", params={"q": "不存在的关键词xyz"})).json()
    assert none["total"] == 0 and none["items"] == []


async def test_search_browser_site_and_url(client, maker, user):
    await _mk_doc(
        maker,
        user,
        "某网页标题",
        source=SourceType.browser,
        site_name="example.com",
        source_url="https://example.com/a/b",
        visit_count=1,
        last_captured_at=datetime.now(timezone.utc),
    )
    await _mk_doc(
        maker,
        user,
        "另一网页",
        source=SourceType.browser,
        site_name="other.org",
        source_url="https://other.org/x",
        visit_count=1,
        last_captured_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    by_site = (
        await client.get("/api/documents", params={"source": "browser", "q": "example.com"})
    ).json()
    assert by_site["total"] == 1
    assert by_site["items"][0]["match"]["type"] == "url"

    # 浏览记录默认按最近浏览时间倒序
    default = (await client.get("/api/documents", params={"source": "browser"})).json()["items"]
    assert default[0]["name"] == "某网页标题"


async def test_search_content_snippet(client, maker, user):
    await _mk_doc(
        maker,
        user,
        "只有正文才有的词",
        chunks=["前面一些无关的铺垫文字，" * 5 + "这里出现稀有词缀zzqk以及后续内容，" + "收尾文字" * 40],
    )
    await _mk_doc(maker, user, "无关书籍", chunks=["完全无关的内容"])

    body = (await client.get("/api/documents", params={"q": "zzqk"})).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["match"]["type"] == "content"
    assert "zzqk" in item["match"]["snippet"]
    assert "…" in item["match"]["snippet"]  # 前后有截断省略
