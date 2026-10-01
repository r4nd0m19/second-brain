"""对话编排（T020）：检索 → 分支（命中/弱相关/库外，FR-005/007）→ 构建 LLM 消息。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.llm import ChatMessage
from app.config import settings
from app.models import AnswerSource, SourceType
from app.retrieval import RetrievedChunk, hybrid_search

# 指代性追问的信号词（T039：拼上一轮问题做检索，提升多轮命中率）
_REFERENTIAL_HINTS = (
    "这本书", "那本书", "这本", "那本", "这个", "那个", "它", "该", "上面",
    "刚", "之前", "前面", "文中", "书里", "这里",
)


def _retrieval_query(user_text: str, history: list[ChatMessage]) -> str:
    """短问句/指代词出现时，拼接上一轮用户问题一起检索（FR-004 多轮上下文）。"""
    last_user = next(
        (h["content"] for h in reversed(history) if h.get("role") == "user"), None
    )
    if last_user and (len(user_text) <= 20 or any(k in user_text for k in _REFERENTIAL_HINTS)):
        return f"{last_user} {user_text}"
    return user_text

SYSTEM_PROMPT = (
    "你是「second-brain」，用户的个人知识助手。规则：\n"
    "1. 若提供了【资料】，优先依据资料回答，并在引用的句子末尾标注对应编号（如 [1]）；"
    "资料不足以回答时明确说明，不要编造资料中没有的内容。\n"
    "2. 若没有提供【资料】，基于你自己的知识回答，如实说明这来自通用知识。\n"
    "3. 全程用中文回答，简洁、准确、直接。"
)


@dataclass
class ReplyPlan:
    source_type: AnswerSource
    citations: list[dict] = field(default_factory=list)
    related_hints: list[dict] = field(default_factory=list)
    llm_messages: list[ChatMessage] = field(default_factory=list)


def _format_hit(index: int, hit: RetrievedChunk) -> str:
    location = hit.heading_path or "—"
    page = f"（第 {hit.page} 页）" if hit.page else ""
    return f"【资料{index}】《{hit.document_name}》· {location}{page}\n{hit.content}"


async def prepare_reply(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    user_text: str,
    history: list[ChatMessage],
) -> ReplyPlan:
    hits = await hybrid_search(session, owner_user_id, _retrieval_query(user_text, history))

    strong = [h for h in hits if h.score >= settings.retrieval_hit_threshold]
    weak = [
        h
        for h in hits
        if settings.retrieval_weak_threshold <= h.score < settings.retrieval_hit_threshold
    ]

    messages: list[ChatMessage] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)

    if strong:  # 命中：基于库内容作答，带出处（FR-005/006）
        # 命中来源全部为既往对话 → 标注 prior_conversation（FR-008 / US3）
        hit_source = (
            AnswerSource.prior_conversation
            if all(h.source_type is SourceType.conversation for h in strong)
            else AnswerSource.kb
        )
        context = "\n\n".join(_format_hit(i + 1, h) for i, h in enumerate(strong))
        messages.append(
            {"role": "user", "content": f"{context}\n\n—— 用户问题：{user_text}"}
        )
        return ReplyPlan(
            source_type=hit_source,
            citations=[h.to_citation() for h in strong],
            llm_messages=messages,
        )

    if weak:  # 弱相关：兜底作答 + 提示（FR-007），弱相关内容不混入主回答
        messages.append({"role": "user", "content": user_text})
        return ReplyPlan(
            source_type=AnswerSource.model_knowledge,
            related_hints=[h.to_citation() for h in weak],
            llm_messages=messages,
        )

    # 库外：纯兜底
    messages.append({"role": "user", "content": user_text})
    return ReplyPlan(source_type=AnswerSource.model_knowledge, llm_messages=messages)
