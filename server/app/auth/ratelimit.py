"""登录失败限速（T034）：进程内滑动窗口实现。

spec NFR Security：登录失败限速（默认 5 次/15 分钟，可配置）。
v1 单进程内实现；多用户/多进程化时替换为 Redis 等共享存储（接口独立，constitution VII 可替换）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import settings

_attempts: dict[str, deque[float]] = defaultdict(deque)
_MAX_KEYS = 4096  # 防滥用膨胀：超限时清掉已过期的键


def check(key: str) -> int | None:
    """未超限返回 None；超限返回建议重试等待秒数。"""
    window = settings.login_rate_window_min * 60
    limit = settings.login_rate_limit
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return int(window - (now - q[0])) + 1
    return None


def record_failure(key: str) -> None:
    if len(_attempts) > _MAX_KEYS:
        for k in [k for k, v in _attempts.items() if not v]:
            _attempts.pop(k, None)
    _attempts[key].append(time.monotonic())


def clear(key: str) -> None:
    _attempts.pop(key, None)
