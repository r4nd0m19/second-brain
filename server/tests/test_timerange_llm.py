"""T039 DoD：LLM 兜底解析——合法输出接受；非法 JSON / 超跨度 / 未来 / 低置信被拒并回退。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.chat.timerange import llm_parse_time_range

TZ = ZoneInfo("Asia/Shanghai")


class _FakeClient:
    def __init__(self, output: str) -> None:
        self.output = output

    async def stream_chat(self, messages):  # noqa: ANN001, ANN201
        yield {"type": "token", "text": self.output}


def _anchor() -> datetime:
    return datetime(2026, 10, 2, 15, 30, tzinfo=TZ)


def _json(start: str, end: str, confidence: float = 0.8, relevant: bool = True) -> str:
    return (
        f'{{"start_iso": "{start}", "end_iso": "{end}", '
        f'"granularity": "week", "confidence": {confidence}, '
        f'"time_relevant": {str(relevant).lower()}}}'
    )


async def test_valid_output_accepted_including_code_fence() -> None:
    client = _FakeClient(
        "```json\n" + _json("2026-09-21T00:00:00+08:00", "2026-09-28T00:00:00+08:00") + "\n```"
    )
    result = await llm_parse_time_range(client, "上个月底看的那篇", _anchor())
    assert result is not None
    assert result.start.day == 21


async def test_invalid_json_rejected() -> None:
    assert await llm_parse_time_range(_FakeClient("这不是 JSON"), "上个月底", _anchor()) is None


async def test_overspan_future_and_low_confidence_rejected() -> None:
    overspan = _json("2010-01-01T00:00:00+08:00", "2026-01-01T00:00:00+08:00")
    assert await llm_parse_time_range(_FakeClient(overspan), "很久以前", _anchor()) is None

    future = _json("2027-01-01T00:00:00+08:00", "2027-02-01T00:00:00+08:00")
    assert await llm_parse_time_range(_FakeClient(future), "明年", _anchor()) is None

    low_conf = _json("2026-09-01T00:00:00+08:00", "2026-10-01T00:00:00+08:00", confidence=0.3)
    assert await llm_parse_time_range(_FakeClient(low_conf), "大概上个月", _anchor()) is None


async def test_start_after_end_and_time_irrelevant_rejected() -> None:
    reversed_range = _json("2026-10-01T00:00:00+08:00", "2026-09-01T00:00:00+08:00")
    assert await llm_parse_time_range(_FakeClient(reversed_range), "倒过来", _anchor()) is None

    irrelevant = _json("2026-09-01T00:00:00+08:00", "2026-10-01T00:00:00+08:00", relevant=False)
    assert await llm_parse_time_range(_FakeClient(irrelevant), "无关", _anchor()) is None
