"""quickstart 场景验收（T032）：SC-001 / SC-003 / SC-004 / SC-005(手动) / SC-006 / SC-007。

覆盖映射见同目录 README.md；SC-002 由 test_sc002_eval.py（包裹 T040 评测脚本）承担，
SC-008 由 test_sc008_backup.py（包裹恢复演练）承担。
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from helpers import cleanup, make_pdf, upload, wait_status
from sc002_eval import ask


@pytest.mark.acceptance
async def test_sc001_upload_index_and_cited_answer(client):
    """SC-001：上传文本型 PDF → 5 分钟内 indexed；SC-002-lite：相关提问带正确出处。"""
    nonce = uuid.uuid4().hex[:8]
    phrase = f"Zephyrion calibration frame {nonce} requires seven lunar samples"
    doc = await upload(client, f"accept-{nonce}.pdf", make_pdf(pages=20, text=phrase))
    doc_id = doc["id"]
    conv_id = None
    try:
        assert doc["status"] == "processing"
        final, elapsed = await wait_status(client, doc_id, {"indexed", "unparseable"})
        assert final["status"] == "indexed", f"应可解析：{final.get('status_reason')}"
        assert elapsed < 300, f"SC-001 超时：{elapsed:.0f}s"

        result = await ask(client, f"Zephyrion calibration frame {nonce} 需要几个月球样本？", None)
        conv_id = result.get("conversation_id")
        assert result["source_type"] == "kb", f"应命中库，实为 {result['source_type']}"
        assert any(c["document_id"] == doc_id for c in result["citations"]), "出处应指向本次上传的资料"
    finally:
        await cleanup(client, doc_id=doc_id, conv_id=conv_id)


@pytest.mark.acceptance
async def test_sc003_sc004_fallback_and_recall(client):
    """SC-003：库外问题兜底（通用知识作答）；SC-004：二次提问命中 prior_conversation。

    选题约束（2026-10-02 修复）：① 通用知识可稳定回答类——F4 后外部信息类问题会先触发联网，
    破坏本用例的"模型知识兜底"语义；② 实测全库最高相似度 <0.5（无弱/强命中）；③ 带随机编号防跨次污染。
    """
    nonce = uuid.uuid4().hex[:6]
    question = f"拜占庭将军问题里，信使可能叛变的情形是如何解决的？（问题编号 {nonce}）"
    conv_id = None
    try:
        first = await ask(client, question, None)
        conv_id = first.get("conversation_id")
        assert first["source_type"] == "model_knowledge", (
            f"库外问题应走兜底，实为 {first['source_type']}"
        )

        import asyncio

        await asyncio.sleep(8)  # 等兜底回写（异步）入库
        second = await ask(client, question, conv_id)
        assert second["source_type"] == "prior_conversation", (
            f"二次提问应命中既往对话，实为 {second['source_type']}"
        )
    finally:
        await cleanup(client, conv_id=conv_id)


@pytest.mark.acceptance
@pytest.mark.skip(reason="手动场景（SC-005）：Windows 浏览器『安装』/ Android 添加主屏；HTTPS 部署后验证应用形态")
async def test_sc005_pwa_install_manual():
    pass


@pytest.mark.acceptance
async def test_sc006_download_checksum(client):
    """SC-006：下载原文件与上传件字节一致（sha256）。"""
    nonce = uuid.uuid4().hex
    payload = (f"second-brain acceptance payload {nonce}; " * 2000).encode()
    digest = hashlib.sha256(payload).hexdigest()
    doc = await upload(client, f"accept-blob-{nonce[:8]}.bin", payload)
    doc_id = doc["id"]
    try:
        resp = await client.get(f"/api/documents/{doc_id}/original")
        assert resp.status_code == 200
        assert hashlib.sha256(resp.content).hexdigest() == digest, "下载内容与上传件不一致"
    finally:
        await cleanup(client, doc_id=doc_id)


@pytest.mark.acceptance
async def test_sc007_unparseable_registered(client):
    """SC-007 / FR-014：无文本层 PDF → 登记为 unparseable（不丢弃）+ 原文件可下载。"""
    nonce = uuid.uuid4().hex[:8]
    doc = await upload(client, f"accept-scan-{nonce}.pdf", make_pdf(pages=2, text=None))
    doc_id = doc["id"]
    try:
        final, _ = await wait_status(client, doc_id, {"indexed", "unparseable"})
        assert final["status"] == "unparseable", "无文本层应判定为无法解析"
        assert final.get("status_reason"), "应给出原因"
        resp = await client.get(f"/api/documents/{doc_id}/original")
        assert resp.status_code == 200, "原文件应仍可下载"
    finally:
        await cleanup(client, doc_id=doc_id)
