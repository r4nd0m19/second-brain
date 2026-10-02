"""对话全文搜索核心（HTTP 端点与 MCP 工具共用）：会话级结果。

命中消息正文（user/assistant 双方），中文子串走 pg_trgm GIN（索引迁移 d51a9c73e2b4）；
排序按各会话"最近一次命中"倒序；`hit` = 该会话最早的命中消息（前端打开后滚动定位）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message
from app.textmatch import like_pattern, make_snippet

HIT_SCAN_LIMIT = 500  # 单次检索的命中消息上限（防"的"类高频词全表拉取）
SEARCH_LIMIT_MAX = 50  # 会话结果条数上限


async def search_conversation_hits(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    q: str,
    limit: int = 20,
) -> dict:
    """按消息正文子串匹配，返回 {items, total}（会话级去重）。"""
    q = q.strip()
    if not q:
        return {"items": [], "total": 0}
    limit = max(1, min(limit, SEARCH_LIMIT_MAX))
    pattern = like_pattern(q)

    rows = (
        await session.execute(
            select(Message, Conversation.title)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.owner_user_id == owner_user_id,
                Message.content.ilike(pattern, escape="\\"),
            )
            .order_by(Message.created_at)
            .limit(HIT_SCAN_LIMIT)
        )
    ).all()

    groups: dict[uuid.UUID, dict] = {}
    for message, title in rows:
        group = groups.get(message.conversation_id)
        if group is None:
            groups[message.conversation_id] = {
                "title": title,
                "hit_count": 1,
                "first": message,
                "last_at": message.created_at,
            }
        else:
            group["hit_count"] += 1
            group["last_at"] = message.created_at

    ordered = sorted(
        groups.items(),
        key=lambda kv: (kv[1]["last_at"] or kv[1]["first"].created_at, str(kv[0])),
        reverse=True,
    )[:limit]

    items = []
    for conv_id, group in ordered:
        first = group["first"]
        items.append(
            {
                "id": str(conv_id),
                "title": group["title"],
                "hit_count": group["hit_count"],
                "last_hit_at": group["last_at"].isoformat() if group["last_at"] else None,
                "hit": {
                    "message_id": str(first.id),
                    "role": first.role.value,
                    "snippet": make_snippet(first.content, q),
                    "created_at": first.created_at.isoformat() if first.created_at else None,
                },
            }
        )
    return {"items": items, "total": len(groups)}
