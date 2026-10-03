"""既往对话引用的来源追溯（2026-10-02 建；2026-10-03 三期 P1 改版为写时留痕）。

背景：对话回写文档只存"问/答"文本，且**回写回答本身无 citations**（回写只发生在模型兜底
回答，FR-008）；后续回答复制这些文本时会带上旧标记。前端把 [N] 硬映射到本轮 citations
会出现误指（指向对话文档本身）或死标（[2][3] 无对应项）。

追溯方式（2026-10-03 起 —— 写时留痕优先，文本匹配仅存量兜底）：
1. **新数据**：回写时（writeback.py）源消息 id 已知——解析结果 {message_id, citations}
   直接存进 `chunks.provenance`，读取时零匹配取用（enrich_citations 的 provenance 分支）；
2. **存量数据**：回填脚本（scripts/backfill_chunk_provenance.py）跑一次同样的解析并入库；
3. **兜底启发式**（仅剩无 provenance 的旧数据；失败返回 None，调用方降级纯文本不误导）：
   以回写块内容（"问：…\\n答：…"）定位原始回答消息 M——全文相等优先、前 120 字前缀兜底；
   M 自带 citations → 直接继承；M 无 citations（复制型）→ 取 M 之前最近一条
   citations 条数 ≥ 文本最大标记编号的助手消息。
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, Message, MessageRole, SourceType

_MARKER_RE = re.compile(r"\[(\d+)\]")
_MAX_SCAN = 50  # 单会话扫描的消息上限（足够覆盖常见会话；防御超长会话）


def _answer_part(chunk_content: str) -> str:
    _, sep, answer = chunk_content.partition("\n答：")
    return answer if sep else chunk_content


def _max_marker(text: str) -> int:
    return max((int(n) for n in _MARKER_RE.findall(text)), default=0)


async def resolve_inherited_citations(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    chunk_content: str,
    message_id: uuid.UUID | None = None,
) -> dict | None:
    """返回 {"message_id": 定位目标消息, "citations": 继承的出处数组或 None}。

    message_id 已知（回写时留痕）→ 直接取该消息为目标，跳过文本匹配；
    否则（存量兜底）按全文/前缀匹配定位。
    """
    answer = _answer_part(chunk_content).strip()
    if not answer:
        return None

    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.assistant,
            )
            .order_by(Message.created_at)
            .limit(_MAX_SCAN)
        )
    ).all()

    target: Message | None = None
    target_index: int | None = None
    if message_id is not None:
        target = await session.get(Message, message_id)
        if target is not None:
            target_index = next((i for i, m in enumerate(rows) if m.id == target.id), None)
    if target is None:  # 存量兜底：全文相等 → 前 120 字前缀
        prefix = answer[:120]
        for index, message in enumerate(rows):
            if message.content == answer:
                target, target_index = message, index
                break
        if target is None:
            for index, message in enumerate(rows):
                if message.content.startswith(prefix):
                    target, target_index = message, index
                    break
    if target is None:
        return None

    if target.citations:  # 自带出处 → 直接继承
        return {"message_id": str(target.id), "citations": target.citations}

    # 复制型回答：向前找最近一条"引用条数 ≥ 文本中最大标记"的助手消息
    need = _max_marker(target.content)
    if need == 0 or target_index is None:
        return {"message_id": str(target.id), "citations": None}
    for message in reversed(rows[:target_index]):
        if message.citations and len(message.citations) >= need:
            return {"message_id": str(target.id), "citations": message.citations}
    return {"message_id": str(target.id), "citations": None}


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def enrich_citations(session: AsyncSession, citations: list[dict] | None) -> None:
    """就地为对话回写来源的引用补 {conversation_id, message_id, inherited_citations}。

    - 生成时（orchestrator）与读取时（历史消息存量数据兜底）共用；
    - 新数据走 chunk.provenance（写时留痕，零匹配）；无 provenance 的旧数据走兜底启发式；
    - 非对话来源引用不动；无法追溯时至少保留 conversation_id（前端降级纯文本，不误指）。
    """
    for citation in citations or []:
        if citation.get("message_id") or citation.get("inherited_citations"):
            continue  # 已补全（新生成的数据）
        conv_id = citation.get("conversation_id")
        if conv_id is None:
            doc_id = citation.get("document_id")
            if not doc_id:  # web 来源等无 document_id：跳过（F4）
                continue
            doc = await session.get(Document, _as_uuid(doc_id))
            if (
                doc is None
                or doc.source_type is not SourceType.conversation
                or doc.conversation_id is None
            ):
                continue
            conv_id = str(doc.conversation_id)
            citation["conversation_id"] = conv_id
        chunk = await session.get(Chunk, _as_uuid(citation.get("chunk_id", "")))
        if chunk is None:
            continue
        if chunk.provenance:  # 写时留痕（新数据）：直接取用
            citation["message_id"] = chunk.provenance.get("message_id")
            if chunk.provenance.get("citations"):
                citation["inherited_citations"] = chunk.provenance["citations"]
            continue
        resolved = await resolve_inherited_citations(session, _as_uuid(conv_id), chunk.content)
        if resolved is None:
            continue
        citation["message_id"] = resolved["message_id"]
        if resolved["citations"]:
            citation["inherited_citations"] = resolved["citations"]
