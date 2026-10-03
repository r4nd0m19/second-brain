"""浏览记录上下文（_browsing_context，FR-012/T049/T050）：站点聚合 + 截断如实说明 + 编号起点。"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.chat.orchestrator import _browsing_context
from app.chat.timerange import TimeRange


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """_browsing_context 的最小桩：scalar→总数；execute→站点聚合；scalars→明细。"""

    def __init__(self, total: int, digest, docs) -> None:
        self._total, self._digest, self._docs = total, digest, docs

    async def scalar(self, *_args, **_kwargs):
        return self._total

    async def execute(self, *_args, **_kwargs):
        return _Result(self._digest)

    async def scalars(self, *_args, **_kwargs):
        return _Result(self._docs)


def _doc(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=f"页面{index}",
        site_name="示例站",
        last_captured_at=datetime(2026, 10, 2, 12, 0, tzinfo=UTC),
        source_url=f"https://e.example/{index}",
    )


def _range() -> TimeRange:
    return TimeRange(
        start=datetime(2026, 9, 30, tzinfo=UTC),
        end=datetime(2026, 10, 3, tzinfo=UTC),
        granularity="day",
        confidence=1.0,
    )


async def test_browsing_context_truncates_over_cap_with_honest_note() -> None:
    docs = [_doc(i) for i in range(51)]
    block, cites = await _browsing_context(
        _Session(66, [("wallhaven.cc", 32), ("bigmodel.cn", 12)], docs),
        uuid.uuid4(),
        _range(),
        start_index=3,
    )

    assert "共 66 条" in block
    assert "仅为最近 50 条" in block  # 截断时不得声称"完整记录"
    assert "wallhaven.cc 32" in block  # 站点聚合
    assert "【资料3】" in block and "【资料52】" in block  # 编号自 start_index 起
    assert "【资料53】" not in block
    assert len(cites) == 50


async def test_browsing_context_full_when_within_cap() -> None:
    docs = [_doc(i) for i in range(20)]
    block, cites = await _browsing_context(
        _Session(20, [("示例站", 20)], docs), uuid.uuid4(), _range(), start_index=1
    )

    assert "全部记录" in block
    assert "仅为最近" not in block
    assert len(cites) == 20


async def test_browsing_context_empty_window_is_honest() -> None:
    block, cites = await _browsing_context(_Session(0, [], []), uuid.uuid4(), _range(), start_index=1)

    assert "没有任何浏览记录" in block
    assert "绝不编造" in block
    assert cites == []
