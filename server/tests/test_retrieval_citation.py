"""T017 DoD：浏览器来源 citation 附链接与浏览时间；上传来源不回归。"""

import uuid
from datetime import datetime, timezone

from app.models import SourceType
from app.retrieval.search import RetrievedChunk


def _chunk(source_type: SourceType, **extra) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="示例",
        source_type=source_type,
        content="内容片段",
        heading_path=None,
        page=None,
        score=0.9,
        **extra,
    )


def test_browser_citation_has_url_and_time() -> None:
    when = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    citation = _chunk(
        SourceType.browser, source_url="https://example.com/a", last_captured_at=when
    ).to_citation()
    assert citation["source_url"] == "https://example.com/a"
    assert citation["last_captured_at"].startswith("2026-10-02")
    assert citation["document_name"] == "示例"


def test_upload_citation_unchanged() -> None:
    citation = _chunk(SourceType.upload).to_citation()
    assert "source_url" not in citation
    assert "last_captured_at" not in citation
    assert set(citation.keys()) == {
        "document_id",
        "chunk_id",
        "document_name",
        "heading_path",
        "page",
        "quote",
    }
