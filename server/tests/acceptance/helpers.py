"""验收测试工具（T032）：极简 PDF 构造、上传/轮询/清理等；F2 增加采集相关助手。"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx


def make_pdf(pages: int = 1, text: str | None = None) -> bytes:
    """构造极简合法 PDF：text=None 时无文本层（模拟扫描版）。文本须为 ASCII 且不含括号。"""
    # 对象编号：1=Catalog 2=Pages 3=Font，之后每页 2 个对象（Page, Contents）
    page_obj_nums = [4 + 2 * i for i in range(pages)]
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i in range(pages):
        content_num = page_obj_nums[i] + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
            ).encode()
        )
        stream = (
            f"BT /F1 14 Tf 72 720 Td ({text} -- page {i + 1}) Tj ET" if text else ""
        ).encode()
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for num, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


async def upload(client: httpx.AsyncClient, name: str, data: bytes) -> dict:
    resp = await client.post(
        "/api/documents", files={"file": (name, data, "application/octet-stream")}
    )
    assert resp.status_code in (200, 201), f"上传失败 {resp.status_code}: {resp.text[:200]}"
    return resp.json()


async def wait_status(
    client: httpx.AsyncClient,
    doc_id: str,
    statuses: set[str],
    timeout: float = 300,
) -> tuple[dict, float]:
    """轮询直到文档达到目标状态；返回 (文档, 耗时秒)。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        docs = (await client.get("/api/documents", params={"page_size": 100})).json()["items"]
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if doc and doc["status"] in statuses:
            return doc, time.monotonic() - t0
        await asyncio.sleep(3)
    raise AssertionError(f"等待 {statuses} 超时（{timeout:.0f}s）：{doc_id}")


async def cleanup(
    client: httpx.AsyncClient,
    *,
    doc_id: str | None = None,
    conv_id: str | None = None,
    token_id: str | None = None,
) -> None:
    """测试产物清理：删文档（级联 chunks/原文件）、对话（级联回写文档）；
    采集凭据吊销后彻底删除（验收库=真实库，不留残留）。"""
    if doc_id:
        await client.delete(f"/api/documents/{doc_id}")
    if conv_id:
        await client.delete(f"/api/conversations/{conv_id}")
    if token_id:
        await client.delete(f"/api/capture/tokens/{token_id}")  # 吊销（立即失效）
        await client.delete(
            f"/api/capture/tokens/{token_id}", params={"purge": "1"}
        )  # 彻底删除


# ── F2 浏览器采集（验收助手）──


def make_html(title: str = "测试页", body: str = "测试内容") -> bytes:
    """极简 HTML 快照（验收用）。"""
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p></body></html>"
    ).encode("utf-8")


async def create_capture_token(client: httpx.AsyncClient, name: str | None = None) -> dict:
    """会话创建采集凭据，返回 {id, name, prefix, token}（明文仅此一次）。"""
    resp = await client.post(
        "/api/capture/tokens", json={"name": name or f"acceptance-{uuid.uuid4().hex[:6]}"}
    )
    assert resp.status_code == 201, f"创建凭据失败 {resp.status_code}: {resp.text[:200]}"
    return resp.json()


async def capture_page(
    client: httpx.AsyncClient,
    token: str,
    *,
    url: str,
    title: str,
    text: str,
    captured_at: str | None = None,
    capture_id: str | None = None,
) -> httpx.Response:
    """模拟扩展上传一条网页（正文 + 快照，multipart 与 SingleFile 格式对齐）。"""
    data: dict[str, str] = {"url": url, "title": title, "text": text}
    if captured_at:
        data["captured_at"] = captured_at
    if capture_id:
        data["capture_id"] = capture_id
    return await client.post(
        "/api/capture/pages",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        files={"file": ("page.html", make_html(title), "text/html")},
    )


async def wait_browser_indexed(client: httpx.AsyncClient, doc_id: str, timeout: float = 180) -> dict:
    """轮询浏览器来源列表直到条目 indexed/unparseable；返回该条目。

    全量翻页（2026-10-03）：列表按 last_captured_at 倒序且 page_size 上限 100——真实浏览库
    超 100 条后，回填的旧条目（如 sc007 的 20 天前页）被挤出第一页，只看首页会永远找不到。
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        doc = None
        page = 1
        while True:
            items = (
                await client.get(
                    "/api/documents",
                    params={"source": "browser", "page_size": 100, "page": page},
                )
            ).json()["items"]
            found = next((d for d in items if d["id"] == doc_id), None)
            if found:
                doc = found
                break
            if len(items) < 100 or page >= 50:  # 到末页（或异常翻页保险）
                break
            page += 1
        if doc and doc["status"] in {"indexed", "unparseable"}:
            return doc
        await asyncio.sleep(2)
    raise AssertionError(f"等待浏览器条目入库超时（{timeout:.0f}s）：{doc_id}")
