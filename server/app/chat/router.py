"""对话端点（T020）：SSE 流式（meta/token/done/error），契约见 contracts/api.md。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.chat.llm import LLMError, estimate_cost_cny, get_llm_client
from app.chat.orchestrator import prepare_reply
from app.chat.writeback import enqueue_writeback
from app.config import settings
from app.db import SessionLocal, get_session
from app.models import AnswerSource, Conversation, Message, MessageRole, User

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息为空")

    if payload.conversation_id is not None:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.owner_user_id == user.id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conversation = Conversation(owner_user_id=user.id, title=text[:20])
        session.add(conversation)
        await session.flush()

    session.add(
        Message(
            conversation_id=conversation.id,
            owner_user_id=user.id,
            role=MessageRole.user,
            content=text,
        )
    )
    await session.commit()

    return StreamingResponse(
        _stream(user.id, conversation.id, conversation.title, text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(
    owner_id: uuid.UUID, conversation_id: uuid.UUID, conversation_title: str, text: str
) -> AsyncIterator[str]:
    llm = get_llm_client()
    async with SessionLocal() as session:
        # 多轮上下文（FR-004）：取最近 N 条历史（含刚保存的当前问题，排除之）
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(settings.chat_history_limit + 1)
            )
        ).all()
        history = [
            {"role": m.role.value, "content": m.content} for m in rows[::-1][:-1]
        ]

        plan = await prepare_reply(session, owner_id, text, history)
        yield _sse(
            "meta",
            {
                "conversation_id": str(conversation_id),
                "source_type": plan.source_type.value,
                "citations": plan.citations,
                "related_hints": plan.related_hints,
                "time_range_label": plan.time_range_label,  # F2 US3：时间解析回显
            },
        )

        parts: list[str] = []
        usage: dict | None = None
        try:
            async for event in llm.stream_chat(plan.llm_messages):
                if event.get("type") == "token":
                    token = event.get("text", "")
                    parts.append(token)
                    yield _sse("token", {"text": token})
                elif event.get("type") == "usage":
                    usage = event.get("usage")
        except LLMError as exc:  # 降级：明确错误 + 可重试（US2 场景 2）
            yield _sse("error", {"code": "llm_error", "message": str(exc)})
            return

        cost_cny = estimate_cost_cny(usage) if usage else None  # FR-017
        assistant = Message(
            conversation_id=conversation_id,
            owner_user_id=owner_id,
            role=MessageRole.assistant,
            content="".join(parts),
            source_type=plan.source_type,
            citations=plan.citations or None,
            related_hints=plan.related_hints or None,
            usage=({**usage, "cost_cny": cost_cny} if usage else None),
        )
        session.add(assistant)
        await session.commit()

        # 兜底/弱相关产生的问答回写检索层（FR-008）；kb 命中的回答不重复入库
        if plan.source_type is AnswerSource.model_knowledge:
            enqueue_writeback(owner_id, conversation_id, conversation_title, text, "".join(parts))

        yield _sse(
            "done",
            {"message_id": str(assistant.id), "usage": usage, "cost_cny": cost_cny},
        )
