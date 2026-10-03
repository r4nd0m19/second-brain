"""兜底问答回写（T026 / FR-008）：把模型兜底产生的问答写入检索层。

- 每个会话对应一条 "对话：{标题}" 资料（source_type=conversation），问答按轮次追加为内容块
- 与解析入库解耦：回写失败只记日志，不阻塞用户（constitution VI）
- 检索命中此类内容时，回答来源标注 prior_conversation（orchestrator）
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import func, select

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
    async with SessionLocal() as session:
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

        content = f"问：{question}\n答：{answer}"
        vector = (await get_embedding_provider().embed([content]))[0]
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


_NO_INFO_MARKERS = (
    "找不到",
    "没有找到",
    "未找到",
    "无法找到",
    "没有看到你",
    "看不到你",
    "无法看到",
    "无法确认你",
    "没有访问你的",
    "没有你的",
    "没有您的",
    "没有关于你",
    "没有关于您",
    "没有收到",
    "没有查到",
)


def is_no_info_answer(answer: str) -> bool:
    """「找不到 / 无权限」类失败回答——不回写（防自污染，2026-10-02 实测）。

    这类回答一旦回写，会成为同类问题检索的最高分命中
    （如 jasonL 查询被「没有找到 jasonL」的回答 0.73 顶置，形成闭环误导）。
    """
    return any(marker in answer for marker in _NO_INFO_MARKERS)


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
