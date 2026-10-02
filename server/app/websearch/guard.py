"""每日搜索次数护栏（F4 成本控制，FR-007）：进程内计数、按日重置（重启清零，单用户够用）。

超限后当天不再联网（静默），问答照常——护栏只做减法，不做故障源。
"""

from __future__ import annotations

from datetime import date

from app.config import settings

_day: date | None = None
_count = 0


def _rollover(today: date) -> None:
    global _day, _count
    if _day != today:
        _day = today
        _count = 0


def allow_search(today: date | None = None) -> bool:
    """今天是否还允许联网搜索（limit ≤ 0 表示不限）。"""
    limit = settings.web_search_daily_limit
    if limit <= 0:
        return True
    _rollover(today or date.today())
    return _count < limit


def record_search(today: date | None = None) -> None:
    """记录一次搜索尝试（在发起请求前调用：失败尝试也计数，防失控）。"""
    global _count
    _rollover(today or date.today())
    _count += 1


def reset_state() -> None:
    """测试用：清空计数。"""
    global _day, _count
    _day = None
    _count = 0
