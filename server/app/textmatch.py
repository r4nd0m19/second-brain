"""列表/搜索共用的文本匹配工具（LIKE 转义与命中片段）。

pg_trgm GIN 索引加速的中文子串匹配（R9）：资料列表（documents/router.py）与
对话搜索（conversations/router.py）共用。
"""

from __future__ import annotations

import re


def like_pattern(q: str) -> str:
    """转义 LIKE 通配符：用户输入按字面量匹配。"""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def make_snippet(content: str, q: str, before: int = 24, after: int = 64) -> str:
    """命中片段（上下文窗口 + 省略号 + 空白折叠）。"""
    idx = content.lower().find(q.lower())
    if idx < 0:
        start, end = 0, min(len(content), before + after)
    else:
        start = max(0, idx - before)
        end = min(len(content), idx + len(q) + after)
    frag = re.sub(r"\s+", " ", content[start:end]).strip()
    return f"{'…' if start > 0 else ''}{frag}{'…' if end < len(content) else ''}"
