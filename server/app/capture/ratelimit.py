"""采集端点限速（F2 FR-014）：按凭据的 60s 滑动窗口（进程内；单用户规模足够）。

限速值 `settings.capture_rate_limit`（每分钟请求数），运行时可调（测试注入）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import settings


class CaptureRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check_and_record(self, key: str) -> int | None:
        """记录一次请求；超限返回建议 Retry-After 秒数（None = 放行）。"""
        limit = settings.capture_rate_limit
        now = time.monotonic()
        queue = self._events[key]
        while queue and now - queue[0] > 60:
            queue.popleft()
        if len(queue) >= limit:
            return max(1, int(queue[0] + 60 - now) + 1)
        queue.append(now)
        return None


capture_limiter = CaptureRateLimiter()
