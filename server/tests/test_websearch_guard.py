"""F4 成本护栏：每日上限 / 跨日重置 / 0=不限。"""

import datetime

from app.config import settings
from app.websearch import guard


def setup_function() -> None:
    guard.reset_state()


def test_limit_and_rollover(monkeypatch) -> None:
    monkeypatch.setattr(settings, "web_search_daily_limit", 2)
    day1 = datetime.date(2026, 10, 2)

    assert guard.allow_search(day1)
    guard.record_search(day1)
    assert guard.allow_search(day1)
    guard.record_search(day1)
    assert not guard.allow_search(day1)  # 达上限

    day2 = day1 + datetime.timedelta(days=1)
    assert guard.allow_search(day2)  # 跨日重置


def test_zero_means_unlimited(monkeypatch) -> None:
    monkeypatch.setattr(settings, "web_search_daily_limit", 0)
    day = datetime.date(2026, 10, 2)
    for _ in range(100):
        assert guard.allow_search(day)
        guard.record_search(day)
