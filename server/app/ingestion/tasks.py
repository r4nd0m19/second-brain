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


def enqueue_ingestion(document_id: uuid.UUID, mode: str = "auto") -> None:
    """调度一次入库（解析+分块+embedding）；不阻塞上传请求（spec NFR）。

    mode: auto（PDF 快通道/其余 Docling）| deep（PDF 走 Docling 分页批处理）。
    注：服务重启会丢失进行中的任务 —— 启动时由 mark_interrupted_documents()
    将遗留的 processing 文档标记为可重试（R7），用户在界面点「重试」显式触发。
    """
    task = asyncio.create_task(ingest_document(document_id, mode))
    _running.add(task)
    task.add_done_callback(_running.discard)
