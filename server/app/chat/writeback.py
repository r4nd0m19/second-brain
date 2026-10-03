"""兜底问答回写（T026 / FR-008）：把模型兜底产生的问答写入检索层。

- 每个会话对应一条 "对话：{标题}" 资料（source_type=conversation），问答按轮次追加为内容块
- 与解析入库解耦：回写失败只记日志，不阻塞用户（constitution VI）
- 检索命中此类内容时，回答来源标注 prior_conversation（orchestrator）
- 回写前经 **LLM 复用性判定**（R18 续三，2026-10-03）：失败说明 / 对用户个人数据的断言
  （浏览记录、身份等——含编造风险）/ 无实质知识的内容不写回。替代此前的标记词表——
  词表补过 4 次仍漏"编造型"（虚构浏览记录不含任何标记词），语义判定是唯一根治。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select

from app.chat.llm import complete_chat, get_llm_client
from app.config import settings
from app.db import SessionLocal
from app.ingestion.embedding import get_embedding_provider
from app.models import Chunk, Document, DocumentStatus, SourceType

logger = logging.getLogger(__name__)

_running: set[asyncio.Task] = set()


async def writeback_exchange(
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_title: str,
    question: str,
    answer: str,
) -> None:
    if not await is_reusable_qa(question, answer):
        logger.info("writeback skipped (LLM judged not reusable): conv=%s", conversation_id)
        return
    async with SessionLocal() as session:
        content = f"问：{question}\n答：{answer}"
        vector = (await get_embedding_provider().embed([content]))[0]

        # 写前近似查重（审计二期 C1）：库内已有 ≥ 阈值的相似内容 → 跳过，防重复问答污染检索
        distance = await session.scalar(
            select(Chunk.embedding.cosine_distance(vector))
            .where(Chunk.owner_user_id == owner_id)
            .order_by(Chunk.embedding.cosine_distance(vector))
            .limit(1)
        )
        if distance is not None and (1.0 - float(distance)) >= settings.writeback_dup_threshold:
            logger.info(
                "writeback skipped (duplicate sim=%.3f): conv=%s",
                1.0 - float(distance),
                conversation_id,
            )
            return

        doc = await session.scalar(
            select(Document).where(
                Document.conversation_id == conversation_id,
                Document.owner_user_id == owner_id,
            )
        )
        if doc is None:
            doc = Document(
                id=uuid.uuid4(),
                owner_user_id=owner_id,
                name=f"对话：{conversation_title[:50]}",
                format="conversation",
                size_bytes=0,
                sha256=f"conversation:{conversation_id}",
                status=DocumentStatus.indexed,
                source_type=SourceType.conversation,
                original_path="",
                conversation_id=conversation_id,
            )
            session.add(doc)
            await session.flush()

        round_no = (
            await session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
            )
        ) or 0

        session.add(
            Chunk(
                document_id=doc.id,
                owner_user_id=owner_id,
                content=content,
                heading_path=f"第 {round_no + 1} 轮",
                embedding=vector,
            )
        )
        await session.commit()
        logger.info("writeback ok: conv=%s round=%d", conversation_id, round_no + 1)


_REUSE_PROMPT = (
    "判断这条问答是否适合写入用户的知识库，供将来检索复用。\n"
    "不适合写回（回答「否」）：① 失败或无能为力的说明（如找不到、没有权限、请用户重发）；"
    "② 对用户个人数据来源的断言（浏览记录、身份、个人资料内容等）——这类事实应由资料库自身提供，"
    "模型转述不可信且包含编造风险；③ 无实质知识的寒暄或流程套话。\n"
    "包含可复用的知识或方法（即使来自通用知识）→「是」。只回答「是」或「否」。"
)


async def is_reusable_qa(question: str, answer: str) -> bool:
    """LLM 复用性判定（R18 续三）；判定失败 → False（保守跳过，防污染优先于防漏写）。"""
    try:
        raw = await complete_chat(
            get_llm_client(),
            [
                {
                    "role": "user",
                    "content": f"{_REUSE_PROMPT}\n\n问：{question[:500]}\n答：{answer[:2000]}",
                }
            ],
        )
    except Exception:  # noqa: BLE001 — 判定失败保守跳过（含 LLMError）
        return False
    return raw.strip().startswith("是")


def enqueue_writeback(
    owner_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_title: str,
    question: str,
    answer: str,
) -> None:
    """异步回写：不阻塞回答的 SSE 流（FR-008）。"""

    async def _run() -> None:
        try:
            await writeback_exchange(
                owner_id, conversation_id, conversation_title, question, answer
            )
        except Exception:  # 回写失败不影响用户（仅记日志）
            logger.exception("writeback failed: conv=%s", conversation_id)

    task = asyncio.create_task(_run())
    _running.add(task)
    task.add_done_callback(_running.discard)
