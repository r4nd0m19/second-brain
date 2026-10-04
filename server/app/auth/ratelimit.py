"""登录失败限速（T034）：进程内滑动窗口实现。

spec NFR Security：登录失败限速（默认 5 次/15 分钟，可配置）。
双键限速（T093 安全审计）：
- `{ip}:{username}` —— 防单账号爆破（原行为）；
- `ip:{ip}` —— 防"随机用户名绕过"（每请求换用户名则单账号键永不触发；且未知用户也跑
  argon2 时序对齐，无 IP 级上限时构成无认证资源耗尽）。
v1 单进程内实现；多用户/多进程化时替换为 Redis 等共享存储（接口独立，constitution VII 可替换）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import settings

_attempts: dict[str, deque[float]] = defaultdict(deque)
_MAX_KEYS = 4096  # 防滥用膨胀：超限时对全部键做过期清理


def _window() -> int:
    return settings.login_rate_window_min * 60


def check(key: str, *, limit: int | None = None) -> int | None:
    """未超限返回 None；超限返回建议重试等待秒数。limit 缺省用单账号口径配置。"""
    window = _window()
    effective = settings.login_rate_limit if limit is None else limit
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= effective:
        return int(window - (now - q[0])) + 1
    return None


def record_failure(key: str) -> None:
    if len(_attempts) > _MAX_KEYS:
        # 全键过期清理（T093：原实现只清"空 deque"，而含过期时间戳的键永不为空 →
        # 从未真正收缩；现按窗口过期逐键清理，杜绝超长用户名等造成的无界增长）
        window = _window()
        now = time.monotonic()
        for k in list(_attempts):
            q = _attempts[k]
            while q and now - q[0] > window:
                q.popleft()
            if not q:
                _attempts.pop(k, None)
    _attempts[key].append(time.monotonic())


def clear(key: str) -> None:
    _attempts.pop(key, None)


def reset_state() -> None:
    """测试辅助：清空全部计数（模块级状态跨测试共享）。"""
    _attempts.clear()
