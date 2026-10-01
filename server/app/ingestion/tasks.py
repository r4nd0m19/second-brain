"""进程内后台任务执行器（T017）。

v1 = 单用户 / 进程内 asyncio 任务；多用户化时替换为独立队列（可替换接口，constitution VII）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.ingestion.pipeline import ingest_document

logger = logging.getLogger(__name__)

_running: set[asyncio.Task] = set()


def enqueue_ingestion(document_id: uuid.UUID) -> None:
    """调度一次入库（解析+分块+embedding）；不阻塞上传请求（spec NFR）。

    注：服务重启会丢失进行中的任务 —— 处于 processing 状态的文档可通过
    reprocess 端点重试（幂等，见 pipeline）。
    """
    task = asyncio.create_task(ingest_document(document_id))
    _running.add(task)
    task.add_done_callback(_running.discard)
