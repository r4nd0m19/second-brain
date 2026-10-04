"""对话端点（T020）：SSE 流式（status/meta/token/done/error），契约见 contracts/api.md。"""

from __future__ import annotations

import asyncio
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
from app.costing import add_llm, start_turn
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

        # 本回合全成本累加器（T079）：流水线中的 LLM/联网/检索费用都记到它上面
        turn_cost = start_turn()

        # 阶段进度（2026-10-03）：规划/检索/扩检/联网都发生在首 token 之前——
        # 经队列把各阶段 status 事件即时转发给客户端（否则该段时间前端只见"…"）
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def on_status(phase: str) -> None:
            queue.put_nowait(phase)

        async def _pipeline():
            try:
                return await prepare_reply(session, owner_id, text, history, on_status)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(_pipeline())
        try:
            while True:
                phase = await queue.get()
                if phase is None:
                    break
                yield _sse("status", {"phase": phase})
            plan = await task  # 流水线异常沿用原有传播语义（流中断，前端有断流提示）
        except BaseException:
            task.cancel()
            raise

        yield _sse(
            "meta",
            {
                "conversation_id": str(conversation_id),
                "source_type": plan.source_type.value,
                "citations": plan.citations,
                "related_hints": plan.related_hints,
                "time_range_label": plan.time_range_label,  # F2 US3：时间解析回显
                "web_failed": plan.web_failed,  # T083：联网未取得结果 → 前端显式提示
                "web_error": plan.web_error,  # 失败原因码（balance/ratelimit/quota/unavailable/no_results）
            },
        )
        yield _sse("status", {"phase": "generating"})

        parts: list[str] = []
        usage: dict | None = None
        try:
            async for event in llm.stream_chat(plan.llm_messages, thinking=True):
                if event.get("type") == "token":
                    token = event.get("text", "")
                    parts.append(token)
                    yield _sse("token", {"text": token})
                elif event.get("type") == "thinking":
                    # 思维链（T088）：流式转发供前端折叠展示；不持久化（仅当次生成可见）
                    yield _sse("thinking", {"text": event.get("text", "")})
                elif event.get("type") == "usage":
                    usage = event.get("usage")
        except LLMError as exc:  # 降级：明确错误 + 可重试（US2 场景 2）
            yield _sse("error", {"code": "llm_error", "message": str(exc)})
            return

        # 全成本（T079）：回答调用按分档定价（R22）计入累加器；流水线期间规划/扩检、
        # 联网按次、embedding/重排在各自调用点已累计 → 快照为 total + 分类明细
        if usage:
            add_llm(estimate_cost_cny(usage))
        total_cny = round(turn_cost.total_cny, 6)
        stored_usage = {
            **(usage or {}),
            "cost_cny": total_cny,
            "cost_breakdown": turn_cost.breakdown(),
        }
        answer_text = "".join(parts)
        assistant = Message(
            conversation_id=conversation_id,
            owner_user_id=owner_id,
            role=MessageRole.assistant,
            content=answer_text,
            source_type=plan.source_type,
            citations=plan.citations or None,
            related_hints=plan.related_hints or None,
            usage=stored_usage,
        )
        session.add(assistant)
        await session.commit()

        # 兜底/弱相关产生的问答回写检索层（FR-008）；kb 命中的回答不重复入库
        # 回写前经 LLM 复用性判定（失败说明/个人数据断言/寒暄不回写；见 writeback.is_reusable_qa、R18 续三）
        if plan.source_type is AnswerSource.model_knowledge:
            enqueue_writeback(
                owner_id, conversation_id, conversation_title, text, answer_text, assistant.id
            )

        yield _sse(
            "done",
            {"message_id": str(assistant.id), "usage": stored_usage, "cost_cny": total_cny},
        )
