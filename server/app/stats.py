"""存储用量统计（试用需求）：数据库 + 磁盘（原文件/快照）——给用户一个总占用的可见视图。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.deps import get_current_user
from app.config import settings
from app.db import get_session
from app.models import Document, User

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/storage")
async def storage_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # T094：资料计数与文件字节**按账号隔离**（原为全表/全目录——单用户时代等价，多账号下
    # 每个用户都会看到他人库的规模；demo 账号截图时实锤）。数据库大小为服务器维度（保留直读）。
    database_bytes = await session.scalar(text("SELECT pg_database_size(current_database())"))

    owner_dir = settings.storage_path / str(user.id)  # 存储按归属分目录（storage/local.py）

    def _disk_scan() -> tuple[int, int, int, int]:
        total = snapshot = files = snapshot_files = 0
        if not owner_dir.exists():
            return total, snapshot, files, snapshot_files
        for dirpath, _dirnames, filenames in os.walk(owner_dir):
            for name in filenames:
                try:
                    size = (Path(dirpath) / name).stat().st_size
                except OSError:
                    continue
                total += size
                files += 1
                if name == "snapshot.html.gz":
                    snapshot += size
                    snapshot_files += 1
        return total, snapshot, files, snapshot_files

    storage_bytes, snapshot_bytes, storage_files, snapshot_files = await run_in_threadpool(
        _disk_scan
    )
    counts = dict(
        (
            await session.execute(
                select(Document.source_type, func.count())
                .where(Document.owner_user_id == user.id)
                .group_by(Document.source_type)
            )
        ).all()
    )
    return {
        "database_bytes": int(database_bytes or 0),
        "storage_bytes": storage_bytes,
        "snapshot_bytes": snapshot_bytes,
        "snapshot_files": snapshot_files,
        "storage_files": storage_files,
        "documents": {source.value: count for source, count in counts.items()},
    }
