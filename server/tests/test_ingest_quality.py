"""分块质量过滤（R17 根治，2026-10-03）：非语言性垃圾块不索引。"""

from types import SimpleNamespace

from app.ingestion.pipeline import _embed_and_store
from app.ingestion.quality import is_indexable
from app.models import DocumentStatus


def test_svg_coordinate_goop_rejected() -> None:
    # 实测样本（浏览器采集页的内联 SVG 坐标/数字海）
    assert not is_indexable("8 89.998222a36.977778 36.977778 0 0 1-73.955556 0c0-11.946667-5.688889")
    assert not is_indexable(
        "4v272.96l133.504-118.784a89.6 89.6 0 0 1 116.864-1.92l119.744 99.84a38.4 38.4 0"
    )
    assert not is_indexable("1,234 5,678 9,012 3,456")


def test_normal_text_kept() -> None:
    assert is_indexable("用户在 2026-10-02 的浏览记录，主要是智谱 BigModel 平台和壁纸网站。")
    assert is_indexable(
        "The architecture decision is essentially a trade-off between consistency and availability."
    )
    assert is_indexable("def foo(x):\n    return x + 1  # 示例代码")


async def test_ingest_junk_only_document_marks_indexed_without_chunks() -> None:
    doc = SimpleNamespace(name="纯垃圾页", status=None, status_reason=None)
    drafts = [
        SimpleNamespace(content="8 89.998222a36.977778 36.977778 0 0 1-73.955556 0c0-11.946667")
    ]
    await _embed_and_store(None, doc, drafts, None)  # type: ignore[arg-type]
    assert doc.status is DocumentStatus.indexed
    assert doc.status_reason and "过滤" in doc.status_reason
