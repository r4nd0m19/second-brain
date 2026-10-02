"""对话编排（T020）：检索 → 分支（命中/弱相关/库外，FR-005/007）→ 构建 LLM 消息。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.llm import ChatMessage, get_llm_client
from app.chat.timerange import (
    TZ,
    TimeRange,
    llm_parse_time_range,
    looks_temporal,
    parse_time_range,
)
from app.config import settings
from app.models import AnswerSource, Document, SourceType
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
    "2. 标注为「网页」的资料来自用户浏览过的页面（含浏览时间与链接）：用户问"
    "「我是否看过 / 最近看过什么」时，直接依据网页资料回答（是 / 否 / 有哪些及时间），"
    "不要声称没有浏览记录的访问权限。\n"
    "3. 标注为「既往对话」的资料是你此前给用户的回答，仅作参考、可能过时或有误；"
    "不要把它当作事实依据（尤其不要据它拒绝回答），与「网页」或普通资料冲突时以后者为准。\n"
    "4. 若没有提供【资料】，基于你自己的知识回答，如实说明这来自通用知识。\n"
    "5. 全程用中文回答，简洁、准确、直接。"
)


@dataclass
class ReplyPlan:
    source_type: AnswerSource
    citations: list[dict] = field(default_factory=list)
    related_hints: list[dict] = field(default_factory=list)
    llm_messages: list[ChatMessage] = field(default_factory=list)
    # F2 US3：时间意图回显（meta 事件携带 → 前端展示，便于用户纠正）
    time_range_label: str | None = None


def _format_hit(index: int, hit: RetrievedChunk) -> str:
    if hit.source_type is SourceType.browser:  # F2：网页来源标注链接与浏览时间
        when = hit.last_captured_at.strftime("%Y-%m-%d") if hit.last_captured_at else "—"
        return f"【资料{index}】网页《{hit.document_name}》（{hit.source_url}，浏览于 {when}）\n{hit.content}"
    if hit.source_type is SourceType.conversation:
        # 既往对话答复：明确标注为参考、非事实来源（防"自我污染"——旧回答被当事实引用）
        return f"【资料{index}】（既往对话答复，仅供参考、可能过时或有误）\n{hit.content}"
    location = hit.heading_path or "—"
    page = f"（第 {hit.page} 页）" if hit.page else ""
    return f"【资料{index}】《{hit.document_name}》· {location}{page}\n{hit.content}"


async def resolve_time_range(user_text: str) -> TimeRange | None:
    """时间意图解析（F2 US3）：规则优先；含时间词但未命中 → LLM 兜底（失败回退无过滤）。"""
    parsed = parse_time_range(user_text)
    if parsed is not None:
        return parsed
    if not looks_temporal(user_text):
        return None
    try:
        return await llm_parse_time_range(get_llm_client(), user_text)
    except Exception:  # noqa: BLE001 — 解析失败不阻塞问答
        return None


def _range_label(time_range: TimeRange) -> str:
    last_moment = (time_range.end - timedelta(seconds=1)).astimezone(TZ)
    return f"{time_range.start.astimezone(TZ):%Y-%m-%d} ~ {last_moment:%Y-%m-%d}"


async def _list_reply(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    user_text: str,
    history: list[ChatMessage],
    time_range: TimeRange,
) -> ReplyPlan:
    """清单意图（"我上周看过哪些网页"）：不走向量检索，直接列浏览记录（FR-012）。"""
    rows = (
        await session.scalars(
            select(Document)
            .where(
                Document.owner_user_id == owner_user_id,
                Document.source_type == SourceType.browser,
                Document.last_captured_at >= time_range.start,
                Document.last_captured_at < time_range.end,
            )
            .order_by(Document.last_captured_at.desc())
            .limit(50)
        )
    ).all()

    messages: list[ChatMessage] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    label = _range_label(time_range)

    if not rows:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"用户想回顾 {label} 浏览过的网页，但该时间段没有任何浏览记录。"
                    f"请如实告知（不要编造任何条目）。用户问题：{user_text}"
                ),
            }
        )
        return ReplyPlan(
            source_type=AnswerSource.model_knowledge, llm_messages=messages, time_range_label=label
        )

    listing = "\n".join(
        f"{index + 1}. 《{doc.name}》· {doc.site_name or '—'} · "
        f"{doc.last_captured_at.astimezone(TZ):%m-%d %H:%M} · {doc.source_url}"
        for index, doc in enumerate(rows)
    )
    citations = [
        {
            "document_id": str(doc.id),
            "chunk_id": None,
            "document_name": doc.name,
            "heading_path": None,
            "page": None,
            "quote": None,
            "source_url": doc.source_url,
            "last_captured_at": doc.last_captured_at.isoformat() if doc.last_captured_at else None,
        }
        for doc in rows
    ]
    messages.append(
        {
            "role": "user",
            "content": (
                f"用户想回顾 {label} 浏览过的网页。系统查询到的完整记录如下（按最近浏览排序）：\n"
                f"{listing}\n\n"
                "请用中文整理成简洁清单（标题 + 浏览时间，可加一句整体概述）；"
                f"不要添加清单之外的条目。用户问题：{user_text}"
            ),
        }
    )
    return ReplyPlan(
        source_type=AnswerSource.kb, citations=citations, llm_messages=messages, time_range_label=label
    )


async def prepare_reply(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    user_text: str,
    history: list[ChatMessage],
) -> ReplyPlan:
    time_range = await resolve_time_range(user_text)
    if time_range is not None and time_range.intent == "list":
        return await _list_reply(session, owner_user_id, user_text, history, time_range)

    hits = await hybrid_search(
        session,
        owner_user_id,
        _retrieval_query(user_text, history),
        captured_after=time_range.start if time_range else None,
        captured_before=time_range.end if time_range else None,
    )
    time_range_label = _range_label(time_range) if time_range is not None else None

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
        if time_range is not None:  # 回显时间范围便于用户纠正（R6）
            question_line = (
                f"（本次检索的时间范围：{_range_label(time_range)}，若与你所想不符请指出）\n"
                f"—— 用户问题：{user_text}"
            )
        else:
            question_line = f"—— 用户问题：{user_text}"
        messages.append({"role": "user", "content": f"{context}\n\n{question_line}"})
        return ReplyPlan(
            source_type=hit_source,
            citations=[h.to_citation() for h in strong],
            llm_messages=messages,
            time_range_label=time_range_label,
        )

    if weak:  # 弱相关：兜底作答 + 提示（FR-007），弱相关内容不混入主回答
        messages.append({"role": "user", "content": user_text})
        return ReplyPlan(
            source_type=AnswerSource.model_knowledge,
            related_hints=[h.to_citation() for h in weak],
            llm_messages=messages,
            time_range_label=time_range_label,
        )

    # 库外：纯兜底
    messages.append({"role": "user", "content": user_text})
    return ReplyPlan(
        source_type=AnswerSource.model_knowledge,
        llm_messages=messages,
        time_range_label=time_range_label,
    )
