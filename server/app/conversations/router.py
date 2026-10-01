"""对话历史端点（T027 / FR-009/011）：列表 / 消息 / 删除。

删除会话 = 级联删除其消息 + 回写资料（含内容块）—— 删除在检索中同步生效。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_session
from app.models import Conversation, Document, Message, User

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _message_dict(message: Message) -> dict:
    return {
        "id": str(message.id),
        "role": message.role.value,
        "content": message.content,
        "source_type": message.source_type.value if message.source_type else None,
        "citations": message.citations,
        "related_hints": message.related_hints,
        "usage": message.usage,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def _owned_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.owner_user_id == user.id
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.get("")
async def list_conversations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.owner_user_id == user.id)
            .order_by(Conversation.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]


@router.get("/{conversation_id}/messages")
async def conversation_messages(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    conversation = await _owned_conversation(session, user, conversation_id)
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        )
    ).all()
    return [_message_dict(m) for m in rows]


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    conversation = await _owned_conversation(session, user, conversation_id)
    # 回写资料（及其内容块）随会话删除 —— 删除同步生效（FR-011）
    await session.execute(
        delete(Document).where(
            Document.conversation_id == conversation.id,
            Document.owner_user_id == user.id,
        )
    )
    await session.delete(conversation)  # messages 由 ORM 级联清理
    await session.commit()
