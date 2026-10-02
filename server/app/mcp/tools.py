"""MCP 工具实现（纯函数：显式接收 session/owner，便于单测直调）。

server.py 的 FastMCP 包装层负责：从上下文取 owner、开 session。
"""

from __future__ import annotations

import uuid

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.conversations.search import search_conversation_hits
from app.models import Chunk, Document
from app.retrieval.search import RetrievedChunk, hybrid_search

SNIPPET_MAX = 600
TOOL_LIMIT_MAX = 30


def _hit_dict(hit: RetrievedChunk) -> dict:
    data = {
        "document_id": str(hit.document_id),
        "name": hit.document_name,
        "source_type": hit.source_type.value,
        "heading": hit.heading_path,
        "page": hit.page,
        "score": round(hit.score, 4),
        "snippet": hit.content[:SNIPPET_MAX],
    }
    if hit.source_url:
        data["source_url"] = hit.source_url
        data["last_captured_at"] = (
            hit.last_captured_at.isoformat() if hit.last_captured_at else None
        )
    return data


async def search_knowledge(
    session: AsyncSession, owner_id: uuid.UUID, query: str, limit: int = 8
) -> list[dict]:
    """混合检索资料/网页/笔记；返回命中片段与出处（含网页链接）。"""
    query = query.strip()
    if not query:
        return []
    hits = await hybrid_search(session, owner_id, query)
    return [_hit_dict(h) for h in hits[: max(1, min(limit, TOOL_LIMIT_MAX))]]


async def get_document(
    session: AsyncSession,
    owner_id: uuid.UUID,
    document_id: str,
    max_chars: int = 20000,
) -> dict:
    """按 id 取文档元信息 + 正文（content.md；缺失时退回内容块拼接）。"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError as exc:
        raise ToolError("document_id 需为 uuid") from exc
    doc = await session.scalar(
        select(Document).where(Document.id == doc_uuid, Document.owner_user_id == owner_id)
    )
    if doc is None:
        raise ToolError("文档不存在或不属于当前用户")

    content = ""
    if doc.original_path:
        path = settings.storage_path / doc.original_path
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
    if not content:  # 回写类文档无原文件：内容块拼接
        rows = (
            await session.scalars(
                select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.created_at)
            )
        ).all()
        content = "\n\n".join(chunk.content for chunk in rows)

    return {
        "document_id": str(doc.id),
        "name": doc.name,
        "format": doc.format,
        "source_type": doc.source_type.value,
        "source_url": doc.source_url,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "truncated": len(content) > max_chars,
        "content": content[:max_chars],
    }


async def search_conversations(
    session: AsyncSession, owner_id: uuid.UUID, query: str, limit: int = 10
) -> list[dict]:
    """搜索历史对话（消息正文），返回会话级命中（含片段与命中数）。"""
    result = await search_conversation_hits(session, owner_id, query, limit)
    return result["items"]
