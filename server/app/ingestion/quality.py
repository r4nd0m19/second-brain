"""分块质量过滤（R17 遗留观察根治，2026-10-03）：剔除不可检索的非语言性垃圾块。

判定：语言字符比 = (CJK + ASCII 字母 + 空白) / 总长 < 0.5 → 不索引。
实测事故：浏览器采集页的内联 SVG 坐标/CSS 数字海（如 "8 89.998222a36.977778 …"）对任意
短问句天然有 0.6+ 的向量相似度，制造大量"假强命中"（"你叫什么名字"也会命中垃圾块）。
"""

from __future__ import annotations

import re

_LINGUISTIC_RE = re.compile(r"[一-鿿A-Za-z\s]")
_MIN_RATIO = 0.5


def is_indexable(text: str) -> bool:
    """语言字符占比达标 → 可索引；纯符号/数字/坐标串等 → 剔除。"""
    if not text:
        return False
    return len(_LINGUISTIC_RE.findall(text)) / len(text) >= _MIN_RATIO
