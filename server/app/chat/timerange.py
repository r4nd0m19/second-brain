"""中文相对时间解析（F2 US3；research R6）：规则层（本模块）+ LLM 兜底（orchestrator）。

契约：`TimeRange {start, end, granularity, confidence}` —— 半开区间 [start, end)；
时区固定 Asia/Shanghai；锚点 = 收到消息的时刻（naive 视为本地时间）。
（2026-10-03 R21：list/search 意图字段随规则路由一并退役，取数方式由查询规划器决定。）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_RE_RECENT_DAYS = re.compile(r"(?:最近|近)\s*([0-9一二两三四五六七八九十]+)\s*天")
_RE_DAYS_AGO = re.compile(r"([0-9一二两三四五六七八九十]+)\s*天前")


@dataclass
class TimeRange:
    start: datetime
    end: datetime
    granularity: str  # day / week / month / year / custom
    confidence: float


def _cn_number(token: str) -> int | None:
    """阿拉伯数字或中文数字（≤99：十 / 十二 / 二十 / 二十三）→ int。"""
    if token.isdigit():
        return int(token)
    if not token or any(ch not in _CN_DIGITS and ch != "十" for ch in token):
        return None
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_DIGITS[left] if left else 1
        ones = _CN_DIGITS[right] if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(token)


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def parse_time_range(text: str, now: datetime | None = None) -> TimeRange | None:
    """规则层解析；未命中返回 None（由调用方决定是否走 LLM 兜底）。"""
    anchor = now if now is not None else datetime.now(TZ)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=TZ)
    anchor = anchor.astimezone(TZ)
    today = anchor.date()

    def result(start: datetime, end: datetime, granularity: str) -> TimeRange:
        return TimeRange(start=start, end=end, granularity=granularity, confidence=0.9)

    # ── N 天（中文/阿拉伯数字）──
    match = _RE_RECENT_DAYS.search(text)
    if match:
        n = _cn_number(match.group(1))
        if n and 1 <= n <= 365:
            return result(_midnight(today - timedelta(days=n - 1)), _midnight(today + timedelta(days=1)), "custom")

    match = _RE_DAYS_AGO.search(text)
    if match:
        n = _cn_number(match.group(1))
        if n and 1 <= n <= 365:
            day = today - timedelta(days=n)
            return result(_midnight(day), _midnight(day + timedelta(days=1)), "day")

    # ── 绝对表达（更长 token 优先）──
    if "上上周" in text:
        monday = today - timedelta(days=today.weekday()) - timedelta(days=14)
        return result(_midnight(monday), _midnight(monday + timedelta(days=7)), "week")
    if "前天" in text:
        day = today - timedelta(days=2)
        return result(_midnight(day), _midnight(day + timedelta(days=1)), "day")
    if "昨天" in text:
        day = today - timedelta(days=1)
        return result(_midnight(day), _midnight(day + timedelta(days=1)), "day")
    if "今天" in text:
        return result(_midnight(today), _midnight(today + timedelta(days=1)), "day")
    if "本周" in text or "这周" in text:
        monday = today - timedelta(days=today.weekday())
        return result(_midnight(monday), _midnight(monday + timedelta(days=7)), "week")
    if "上周" in text:
        monday = today - timedelta(days=today.weekday()) - timedelta(days=7)
        return result(_midnight(monday), _midnight(monday + timedelta(days=7)), "week")
    if "上个月" in text or "上月" in text:
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month
        last_month_start = (first_this_month - timedelta(days=1)).replace(day=1)
        return result(_midnight(last_month_start), _midnight(last_month_end), "month")
    if "本月" in text or "这个月" in text:
        first = today.replace(day=1)
        next_first = (first + timedelta(days=32)).replace(day=1)
        return result(_midnight(first), _midnight(next_first), "month")
    if "去年" in text:
        return result(datetime(today.year - 1, 1, 1, tzinfo=TZ), datetime(today.year, 1, 1, tzinfo=TZ), "year")
    if "今年" in text:
        return result(datetime(today.year, 1, 1, tzinfo=TZ), datetime(today.year + 1, 1, 1, tzinfo=TZ), "year")

    return None


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


async def llm_parse_time_range(client, text: str, now: datetime | None = None) -> TimeRange | None:
    """LLM 兜底（T039）：严格 JSON → 校验（start<end、跨度 ≤ N 年、非未来、置信度 ≥0.5）。

    任一校验不过 → None（调用方回退为无时间过滤，不静默使用可疑解析）。
    """
    from app.chat.llm import complete_chat  # 延迟导入：避免模块环
    from app.config import settings

    anchor = now if now is not None else datetime.now(TZ)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=TZ)
    anchor = anchor.astimezone(TZ)
    weekday = "一二三四五六日"[anchor.weekday()]

    prompt = (
        "你是时间表达解析器。请把用户问题中的时间表达解析为半开区间 [start, end)。\n"
        f"当前时间：{anchor:%Y-%m-%d %H:%M}（周{weekday}），时区 Asia/Shanghai。\n"
        "只输出严格 JSON（不要解释、不要代码块）：\n"
        '{"start_iso": "YYYY-MM-DDTHH:MM:SS+08:00" 或 null, "end_iso": "同上 或 null", '
        '"granularity": "day|week|month|year|custom", "confidence": 0到1的小数, '
        '"time_relevant": true 或 false}\n'
        "time_relevant：时间表达用于限定检索范围时为 true；若时间只是顺带提及、并非要按时间过滤 → false。\n"
        "start 必须早于 end；无法确定时间时 start_iso/end_iso 置 null。\n"
        f"用户问题：{text}"
    )
    try:
        raw = await complete_chat(client, [{"role": "user", "content": prompt}])
    except Exception:  # noqa: BLE001 — LLM 故障 → 回退无过滤
        return None

    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    if not data.get("time_relevant"):
        return None  # 时间只是顺带提及 → 不作为过滤条件
    start_raw, end_raw = data.get("start_iso"), data.get("end_iso")
    if not start_raw or not end_raw:
        return None
    try:
        start = datetime.fromisoformat(str(start_raw))  # py3.11+ 原生支持 "Z" 后缀
        end = datetime.fromisoformat(str(end_raw))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=TZ)
    if end.tzinfo is None:
        end = end.replace(tzinfo=TZ)

    if not start < end:
        return None
    if end - start > timedelta(days=365 * settings.timerange_max_years):
        return None
    if start > anchor + timedelta(days=1):  # "看过"语义：未来时间无效
        return None
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.5:
        return None

    return TimeRange(
        start=start,
        end=end,
        granularity=str(data.get("granularity") or "custom"),
        confidence=confidence,
    )
