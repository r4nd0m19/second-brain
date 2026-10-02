"""联网决策（F4）：是否需要搜索 + 搜索词改写。

隐私边界（FR-006）：**只接收当前用户问题**（不含对话历史/本地库内容）。
容错（NFR）：任何失败 → 不搜索（联网永远不阻塞问答）。
"""

from __future__ import annotations

from app.chat.llm import LLMError, get_llm_client

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "联网搜索网页（仅在需要外部/实时信息时调用）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "改写后的简洁搜索词（不超过 70 字符，保留关键实体）",
                }
            },
            "required": ["query"],
        },
    },
}

_PLANNER_SYSTEM = (
    "你是检索决策器：判断回答用户的问题是否需要联网搜索。\n"
    "必须调用 web_search 的情况：问题涉及外部/实时信息——人物或组织近况、最新事件与行情、"
    "站外资源与链接推荐、他人主页、行业动态，或你自身知识可能过时/不确定的内容。\n"
    "用户显式要求联网搜索时（如「联网搜一下 X」「上网查 X」「帮我搜 X」「搜索一下 X」）："
    "只要消息里有可检索的主题，即使你认为自己能回答也必须调用，检索词为主题改写；"
    "若用户意在检索自己的本地资料/记录（如「搜一下我的资料」），不要调用。\n"
    "不要调用的情况：概念解释、定义、原理、数学、代码写法、常识等通用知识问题——"
    "即使你自认为细节不完全确定，也凭自身知识回答，一般不联网。\n"
    "整条消息没有任何可检索内容时（如只说「发起联网搜索」），只回复 NO_SEARCH；不要编造搜索结果。"
)


async def decide_search(user_text: str) -> dict:
    """返回 {"search": bool, "query": str}；失败容错为不搜索。"""
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    try:
        result = await get_llm_client().complete_with_tools(
            messages, tools=[WEB_SEARCH_TOOL], tool_choice="auto", max_tokens=120
        )
    except LLMError:
        return {"search": False, "query": ""}

    for call in result.get("tool_calls") or []:
        if call.get("name") == "web_search":
            query = str((call.get("arguments") or {}).get("query") or "").strip()[:70]
            if query:
                return {"search": True, "query": query}
    return {"search": False, "query": ""}
