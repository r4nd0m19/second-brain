"""二段式重排（R24/A 方案）：分数替换与失败降级。"""

import uuid

from app.config import settings
from app.models import SourceType
from app.retrieval import search as search_mod
from app.retrieval.search import RetrievedChunk


def _chunk(name: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name=name,
        source_type=SourceType.upload,
        content=f"{name} 的正文内容",
        heading_path=None,
        page=None,
        score=score,
    )


async def test_rerank_replaces_scores_and_order(monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)

    async def fake_api(query: str, docs: list[str]) -> list[float]:
        assert query == "问题"
        assert len(docs) == 2
        return [0.1, 0.9]  # 第二段重排分更高

    monkeypatch.setattr(search_mod, "_rerank_api", fake_api)
    out = await search_mod._apply_rerank("问题", [_chunk("A", 0.8), _chunk("B", 0.2)])
    assert out is not None
    assert [c.document_name for c in out] == ["B", "A"]
    assert abs(out[0].score - 0.9) < 1e-9


async def test_rerank_failure_degrades(monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)

    async def boom(query: str, docs: list[str]) -> list[float]:
        raise RuntimeError("api down")

    monkeypatch.setattr(search_mod, "_rerank_api", boom)
    assert await search_mod._apply_rerank("q", [_chunk("A", 0.8)]) is None


async def test_rerank_disabled_skips(monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", False)
    assert await search_mod._apply_rerank("q", [_chunk("A", 0.8)]) is None
