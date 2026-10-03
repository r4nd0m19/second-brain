"""查询规划器（FR-022，2026-10-03）：用工具调用决定"这句话该怎么从资料库/互联网取数"。

取代此前的句式规则路由（清单/语义意图词表、显式联网指令正则）——分类由 LLM 完成，
新增句式天然覆盖；失败/未规划 → 调用方回退默认检索基线（规划器只是基线之上的优化）。
护栏：最多 3 个工具、单轮不循环、工具参数类型化（禁自由拼 SQL）。
隐私：仅发送当前问题（与既有边界一致）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.chat.llm import LLMError, get_llm_client

logger = logging.getLogger(__name__)

MAX_CALLS = 3  # 单轮工具上限（延迟硬约束）

PLANNER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": "在用户的个人资料库（已入库的资料/浏览网页/笔记/既往对话）中做语义检索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "简洁检索词（不超过 70 字符，保留关键实体，可中英对照）",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "可选时间限定，自然语言（如「昨天」「上周」「最近三天」）；无时间含义时省略",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_browsing",
            "description": "列出用户浏览记录的清单（某时间段看过哪些网页，含站点统计）。用户问浏览历史（看了什么/浏览了哪些）时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_range": {
                        "type": "string",
                        "description": "时间范围，自然语言（如「昨天」「上周」「最近三天」）",
                    }
                },
                "required": ["time_range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索外部信息。用户明确要求联网，或问题涉及外部/实时信息而资料库无法回答时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "简洁搜索词（不超过 70 字符，保留关键实体）",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

_PLANNER_SYSTEM = (
    "你是检索规划器：为回答用户问题，规划从用户个人资料库与互联网取数的工具调用"
    "（最多 3 个，可按需组合；也可以不调用任何工具）。规则：\n"
    "① 问浏览历史（看过什么 / 浏览了什么 / 看了哪些）→ list_browsing（必须带时间词）。\n"
    "② 找资料内容、知识、既往对话 → search_library（可带时间限定）；可为同一问题给出 1-2 条不同措辞的 query 提高召回。\n"
    "③ 联网搜索：用户明确要求联网（如「联网搜一下 X」）必须调用 web_search；问题涉及外部/实时信息"
    "（人物或组织近况、最新事件与行情、站外资源与链接、他人主页）且资料库无法回答时也应调用；"
    "概念解释、定义、原理、数学、代码写法、常识等通用知识问题不要联网；"
    "若用户意在检索自己的本地资料/记录（如「搜一下我的资料」），改用 search_library。\n"
    "④ 用户要求联网但没有具体可搜内容（如只发「发起联网搜索」）→ 不调用任何工具。\n"
    "⑤ 纯闲聊/寒暄 → 不调用任何工具。\n"
    "query 用简洁检索词（保留关键实体）；不要编造检索词。"
)

_TOOL_NAMES = {tool["function"]["name"] for tool in PLANNER_TOOLS}


@dataclass
class PlannedCall:
    name: str
    args: dict = field(default_factory=dict)


async def plan_retrieval(user_text: str) -> list[PlannedCall]:
    """规划取数工具调用；失败/无调用时返回 []（调用方回退基线路径）。"""
    try:
        result = await get_llm_client().complete_with_tools(
            [
                {"role": "system", "content": _PLANNER_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            tools=PLANNER_TOOLS,
            tool_choice="auto",
            max_tokens=240,
        )
    except LLMError:
        return []

    calls: list[PlannedCall] = []
    for raw in result.get("tool_calls") or []:
        name = str(raw.get("name") or "")
        if name not in _TOOL_NAMES:
            continue
        args = raw.get("arguments")
        calls.append(PlannedCall(name=name, args=args if isinstance(args, dict) else {}))
        if len(calls) >= MAX_CALLS:
            break
    if calls:
        logger.info("retrieval plan: %s", [(c.name, c.args.get("query") or c.args.get("time_range")) for c in calls])
    return calls
