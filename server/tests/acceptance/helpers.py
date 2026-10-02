"""验收测试工具（T032）：极简 PDF 构造、上传/轮询/清理等。"""

from __future__ import annotations

import asyncio
import time

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
        docs = (await client.get("/api/documents")).json()
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if doc and doc["status"] in statuses:
            return doc, time.monotonic() - t0
        await asyncio.sleep(3)
    raise AssertionError(f"等待 {statuses} 超时（{timeout:.0f}s）：{doc_id}")


async def cleanup(client: httpx.AsyncClient, *, doc_id: str | None = None, conv_id: str | None = None) -> None:
    """测试产物清理：删文档（级联 chunks/原文件）与对话（级联回写文档）。"""
    if doc_id:
        await client.delete(f"/api/documents/{doc_id}")
    if conv_id:
        await client.delete(f"/api/conversations/{conv_id}")
