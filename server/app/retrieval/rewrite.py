"""低置信多查询重试（R19，2026-10-02）：把问题改写为多条检索变体，多路召回合并。

实测驱动：单条改写不可靠（「我的技术栈」单改写变体仅 0.565）；2-3 条多样变体扇出后
可命中原本检索不到的库内答案（profile 页 0.53 → 变体 0.616 + 关键词加成 0.736）。
仅做检索扩检；改写失败/超时 → 返回空列表（调用方维持原行为，不阻塞问答）。
隐私：改写仅发送当前问题（同 web 决策器边界）。
"""

from __future__ import annotations

import re

from app.chat.llm import LLMError, complete_chat, get_llm_client

# 变体上限（成本/延迟约束；实测 2-3 条足够）
MAX_VARIANTS = 3

_EXPAND_SYSTEM = (
    "你是检索查询扩写器。把用户的问题改写为 2 到 3 条用于在用户个人资料库中检索的查询。"
    "要求：① 保留原问题的关键实体与意图，不引入新主题；② 换用不同措辞，或补充同义/中英文对照表达；"
    "③ 若问题涉及用户本人（如「我的/我是」开头），至少一条变体应从「个人主页 / 个人资料 / profile 简介」"
    "的角度改写；④ 每行一条，不超过 30 字；⑤ 只输出查询本身，不要编号、不要解释。"
)

_MARKER_RE = re.compile(r"^\s*(?:[-•*]\s*)?(?:\d{1,2}\s*[.、)）]\s*)?")


async def expand_queries(user_text: str) -> list[str]:
    """生成 2-3 条检索变体；失败或无有效变体时返回 []（调用方按原路径继续）。"""
    try:
        raw = await complete_chat(
            get_llm_client(),
            [
                {"role": "system", "content": _EXPAND_SYSTEM},
                {"role": "user", "content": user_text},
            ],
        )
    except LLMError:
        return []

    variants: list[str] = []
    seen = {user_text.strip()}
    for line in raw.splitlines():
        cleaned = _MARKER_RE.sub("", line).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        variants.append(cleaned[:70])
        if len(variants) >= MAX_VARIANTS:
            break
    return variants
