"""清单回复的截断语义（2026-10-02）：窗口内 >50 条时只列 50 条，且如实说明未列全。

驱动来源：sc007 验收在"窗口内条目超过 50"的真实数据下失败（假阳性的"完整记录"口径）。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.chat.orchestrator import _list_reply
from app.chat.timerange import TimeRange


class _Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """只实现 _list_reply 用到的 scalars（忽略 select 语句本身）。"""

    def __init__(self, rows) -> None:
        self._rows = rows

    async def scalars(self, *_args, **_kwargs):
        return _Result(self._rows)


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


async def test_list_reply_truncates_over_cap_with_honest_note() -> None:
    rows = [_doc(i) for i in range(51)]
    plan = await _list_reply(_Session(rows), uuid.uuid4(), "我最近3天看过哪些网页", [], _range())

    content = plan.llm_messages[-1]["content"]
    assert "超过 50 条" in content  # 截断时不得声称"完整记录"
    assert "完整记录" not in content
    assert "页面49" in content and "页面50" not in content  # 只列前 50 条
    assert len(plan.citations) == 50


async def test_list_reply_full_when_within_cap() -> None:
    rows = [_doc(i) for i in range(50)]
    plan = await _list_reply(_Session(rows), uuid.uuid4(), "我最近3天看过哪些网页", [], _range())

    content = plan.llm_messages[-1]["content"]
    assert "完整记录" in content
    assert "超过 50 条" not in content
    assert len(plan.citations) == 50
