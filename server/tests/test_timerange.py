"""T037：中文相对时间规则解析单测（半开区间；周一为周首；跨年/跨月；锚点=消息时刻）。"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.chat.timerange import parse_time_range

TZ = ZoneInfo("Asia/Shanghai")


def _anchor(y: int = 2026, m: int = 10, d: int = 2, hh: int = 15) -> datetime:
    return datetime(y, m, d, hh, 30, tzinfo=TZ)


def _midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def test_today_yesterday_and_before_yesterday() -> None:
    now = _anchor()
    today = now.date()

    r = parse_time_range("我今天的浏览", now)
    assert r is not None and r.start == _midnight(today) and r.end == _midnight(today + timedelta(days=1))

    r = parse_time_range("昨天看过的那篇", now)
    assert r is not None
    assert r.start == _midnight(today - timedelta(days=1))
    assert r.end - r.start == timedelta(days=1)  # 半开区间恰好一天

    r = parse_time_range("前天", now)
    assert r is not None and r.start == _midnight(today - timedelta(days=2))


def test_this_week_and_last_week_monday_start() -> None:
    now = _anchor()
    monday = now.date() - timedelta(days=now.weekday())  # 周一为周首
    assert monday.weekday() == 0

    r = parse_time_range("本周看过的", now)
    assert r is not None and r.start == _midnight(monday) and r.end == _midnight(monday + timedelta(days=7))

    r = parse_time_range("上周看过哪些网页", now)
    assert r is not None
    assert r.start == _midnight(monday - timedelta(days=7))
    assert r.end == _midnight(monday)
    assert r.intent == "list"


def test_last_week_crosses_year_boundary() -> None:
    now = _anchor(2026, 1, 1)  # 元旦：上周落在 2025-12
    monday = now.date() - timedelta(days=now.weekday())
    r = parse_time_range("上周", now)
    assert r is not None
    assert r.start == _midnight(monday - timedelta(days=7))
    assert r.start.year in (2025, 2026)  # 跨年不越界


def test_recent_n_days_and_n_days_ago_with_chinese_numerals() -> None:
    now = _anchor()
    today = now.date()

    r = parse_time_range("最近3天看过的", now)
    assert r is not None
    assert r.start == _midnight(today - timedelta(days=2))  # 含今天共 3 天
    assert r.end == _midnight(today + timedelta(days=1))

    r_cn = parse_time_range("最近七天看过的", now)
    assert r_cn is not None and r_cn.start == _midnight(today - timedelta(days=6))

    r = parse_time_range("3 天前看的那篇文章", now)
    assert r is not None
    assert r.start == _midnight(today - timedelta(days=3))
    assert r.end - r.start == timedelta(days=1)

    r_cn = parse_time_range("三天前", now)
    assert r_cn is not None and r_cn.start == _midnight(today - timedelta(days=3))


def test_last_month_crosses_year_boundary() -> None:
    now = _anchor(2026, 1, 15)
    r = parse_time_range("上个月", now)
    assert r is not None
    assert r.start == datetime(2025, 12, 1, tzinfo=TZ)
    assert r.end == datetime(2026, 1, 1, tzinfo=TZ)


def test_this_year() -> None:
    r = parse_time_range("今年", _anchor())
    assert r is not None
    assert r.start == datetime(2026, 1, 1, tzinfo=TZ)
    assert r.end == datetime(2027, 1, 1, tzinfo=TZ)


def test_intent_list_vs_search_vs_none() -> None:
    now = _anchor()
    assert parse_time_range("我上周看过哪些网页？", now).intent == "list"
    assert parse_time_range("上周看过的文章里关于中间件的部分", now).intent == "search"
    assert parse_time_range("什么是 RAG？", now) is None


def test_naive_now_is_localized() -> None:
    r = parse_time_range("昨天", datetime(2026, 10, 2, 15, 30))
    assert r is not None and r.start.tzinfo is not None
