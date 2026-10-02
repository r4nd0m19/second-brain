"""T040 DoD：带时间窗口的混合检索——命中全部落在 [after, before) 内。"""

import uuid
from datetime import datetime, timedelta, timezone

import app.retrieval.search as search_module
from app.config import settings
from app.models import Chunk, Document, DocumentStatus, SourceType, User
from app.retrieval.search import hybrid_search


class _FakeEmbedding:
    async def embed(self, texts, on_progress=None):  # noqa: ANN001, ANN201
        return [[0.1] * settings.embedding_dim for _ in texts]


def _browser_doc(user_id, name: str, url: str, captured: datetime) -> Document:
    return Document(
        owner_user_id=user_id,
        name=name,
        format="html",
        size_bytes=1,
        sha256=str(uuid.uuid4()),
        status=DocumentStatus.indexed,
        source_type=SourceType.browser,
        original_path="p",
        source_url=url,
        site_name="example.com",
        first_captured_at=captured,
        last_captured_at=captured,
        visit_count=1,
    )


async def test_time_filtered_search_only_in_window(session, monkeypatch) -> None:
    monkeypatch.setattr(search_module, "get_embedding_provider", lambda: _FakeEmbedding())

    user = User(username=f"tf-{uuid.uuid4().hex[:8]}", password_hash="x")
    session.add(user)
    await session.flush()

    anchor = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    doc_in = _browser_doc(user.id, "窗口内教程", "https://in.example/a", anchor)
    doc_out = _browser_doc(user.id, "窗口外教程", "https://out.example/b", anchor - timedelta(days=30))
    session.add_all([doc_in, doc_out])
    await session.flush()
    for doc in (doc_in, doc_out):
        session.add(
            Chunk(
                document_id=doc.id,
                owner_user_id=user.id,
                content="检索增强生成的中间件鉴权说明",
                embedding=[0.1] * settings.embedding_dim,
            )
        )
    await session.commit()

    results = await hybrid_search(
        session,
        user.id,
        "检索增强 中间件鉴权",
        captured_after=anchor - timedelta(days=1),
        captured_before=anchor + timedelta(days=1),
    )
    assert results
    assert all(r.document_id == doc_in.id for r in results)
    assert all(r.source_url == "https://in.example/a" for r in results)

    # 无过滤时两条都会进入候选（回归：F1 行为不变）
    results_all = await hybrid_search(session, user.id, "检索增强 中间件鉴权")
    assert {r.document_id for r in results_all} == {doc_in.id, doc_out.id}
