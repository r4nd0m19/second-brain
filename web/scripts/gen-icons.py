#!/usr/bin/env python3
"""生成 PWA 图标（纯 Python 标准库，无第三方依赖）。

设计：深色底（#0f1115）+ 神经网络节点图形（accent #5b8cff / 浅紫 #b1b9f9）。
产出（web/public/）：
    icon-192.png / icon-512.png / icon-maskable-512.png / apple-touch-icon-180.png
运行：python3 web/scripts/gen-icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (15, 17, 21)
ACCENT = (91, 140, 255)
SOFT = (177, 185, 249)

# 单位坐标（0..1）中的节点与连线
NODES = [
    (0.30, 0.34), (0.68, 0.30), (0.50, 0.50), (0.28, 0.66),
    (0.70, 0.68), (0.52, 0.20), (0.50, 0.82),
]
EDGES = [(0, 2), (1, 2), (3, 2), (4, 2), (5, 0), (5, 1), (6, 3), (6, 4), (0, 1)]
MASTER = 1536
PUBLIC = Path(__file__).resolve().parent.parent / "public"


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / (vx * vx + vy * vy))) if (vx or vy) else 0.0
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return (dx * dx + dy * dy) ** 0.5


def render_master(content_scale: float) -> bytearray:
    """渲染 MASTER×MASTER 主图（RGBA）。content_scale 控制图形占总幅比例（maskable 用更小值）。"""
    s = MASTER
    # 几何：单位图形 → 画布像素（围绕中心缩放）
    k = s * content_scale
    off = (s - k) / 2
    nodes = [(off + x * k, off + y * k) for x, y in NODES]
    line_w = s * 0.011
    node_r = s * 0.030
    center_r = s * 0.042
    aa = 1.2  # 抗锯齿边缘（像素）

    buf = bytearray()
    for y in range(s):
        buf.append(0)  # PNG 行滤波字节
        for x in range(s):
            r, g, b = BG
            fx, fy = x + 0.5, y + 0.5
            # 连线
            for i, j in EDGES:
                ax, ay = nodes[i]
                bx, by = nodes[j]
                d = _seg_dist(fx, fy, ax, ay, bx, by)
                a = max(0.0, min(1.0, (line_w - d) / aa + 0.5)) * 0.55
                if a > 0:
                    r = r + (ACCENT[0] - r) * a
                    g = g + (ACCENT[1] - g) * a
                    b = b + (ACCENT[2] - b) * a
            # 节点
            for idx, (nx, ny) in enumerate(nodes):
                radius = center_r if idx == 2 else node_r
                color = SOFT if idx == 2 else ACCENT
                dd = ((fx - nx) ** 2 + (fy - ny) ** 2) ** 0.5
                a = max(0.0, min(1.0, (radius - dd) / aa + 0.5))
                if a > 0:
                    r = r + (color[0] - r) * a
                    g = g + (color[1] - g) * a
                    b = b + (color[2] - b) * a
            buf += bytes((int(r + 0.5), int(g + 0.5), int(b + 0.5), 255))
    return buf


def resample(master: bytearray, size: int) -> bytearray:
    """区域平均降采样（含小数倍率）。"""
    f = MASTER / size
    row_bytes = MASTER * 4 + 1
    out = bytearray()
    for ty in range(size):
        out.append(0)
        y0, y1 = ty * f, (ty + 1) * f
        for tx in range(size):
            x0, x1 = tx * f, (tx + 1) * f
            r = g = b = wsum = 0.0
            for sy in range(int(y0), min(int(y1) + 1, MASTER)):
                wy = min(sy + 1, y1) - max(sy, y0)
                if wy <= 0:
                    continue
                base = sy * row_bytes + 1
                for sx in range(int(x0), min(int(x1) + 1, MASTER)):
                    wx = min(sx + 1, x1) - max(sx, x0)
                    if wx <= 0:
                        continue
                    w = wx * wy
                    p = base + sx * 4
                    r += master[p] * w
                    g += master[p + 1] * w
                    b += master[p + 2] * w
                    wsum += w
            out += bytes((int(r / wsum + 0.5), int(g / wsum + 0.5), int(b / wsum + 0.5), 255))
    return out


def write_png(path: Path, size: int, pixels: bytearray) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # RGBA8
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"  {path.name}: {size}x{size}, {len(png) / 1024:.1f} KB")


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    print("渲染主图（1536²，约 1 分钟）…")
    normal = render_master(0.84)
    maskable = render_master(0.62)  # maskable 安全区
    for size in (512, 192):
        write_png(PUBLIC / f"icon-{size}.png", size, resample(normal, size))
    write_png(PUBLIC / "apple-touch-icon-180.png", 180, resample(normal, 180))
    write_png(PUBLIC / "icon-maskable-512.png", 512, resample(maskable, 512))


if __name__ == "__main__":
    main()
