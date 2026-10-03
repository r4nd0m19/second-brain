"""一次性回填：给存量对话回写块补写 provenance（三期 P1，2026-10-03）。

用法：cd server && .venv/bin/python scripts/backfill_chunk_provenance.py

- 幂等：只处理 source_type=conversation 且 provenance IS NULL 的内容块；
- 复用 inherit.resolve_inherited_citations 的存量兜底匹配（全文/前缀 + 向前扫描）；
- 匹配不到的块保持 NULL（读取时行为不变：安全降级纯文本）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.chat.inherit import resolve_inherited_citations
from app.db import SessionLocal
from app.models import Chunk, Document, SourceType


async def main() -> None:
    scanned = updated = skipped = 0
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Chunk, Document)
                .join(Document, Chunk.document_id == Document.id)
                .where(
                    Document.source_type == SourceType.conversation,
                    Chunk.provenance.is_(None),
                )
            )
        ).all()
        for chunk, doc in rows:
            scanned += 1
            if doc.conversation_id is None:
                skipped += 1
                continue
            resolved = await resolve_inherited_citations(
                session, doc.conversation_id, chunk.content
            )
            if resolved is None:
                skipped += 1
                continue
            chunk.provenance = resolved
            updated += 1
        await session.commit()
    print(f"provenance backfill: scanned={scanned} updated={updated} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
