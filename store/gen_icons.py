#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验真 · 图标生成器
=================
纯标准库实现（不依赖 Pillow / cairo），生成 16/32/48/128 四种尺寸的 PNG 图标。

图案：深色圆角方块 + 白色放大镜 + 镜片内绿色对勾
  —— 放大镜 = "查"，对勾 = "可信"，一眼能懂，缩到 16px 也认得出。

用法：
    python store/gen_icons.py

输出：
    extension/icons/icon16.png / icon32.png / icon48.png / icon128.png
"""

import os
import struct
import zlib

# ── 配色（与扩展界面一致）─────────────────────────────────
BG     = (0x11, 0x18, 0x27)   # #111827  深墨蓝，和 options.html 的主色一致
WHITE  = (0xFF, 0xFF, 0xFF)
GREEN  = (0x22, 0xC5, 0x5E)   # #22C55E  可信的绿

# ── 图案几何（归一化坐标，0~1，x 向右 y 向下）──────────────
CORNER_R   = 0.22             # 圆角半径
LENS_C     = (0.44, 0.42)     # 镜片圆心
LENS_R_OUT = 0.305            # 镜片外径
LENS_R_IN  = 0.215            # 镜片内径（环宽 = 外径 - 内径）
HANDLE     = ((0.630, 0.610), (0.828, 0.808), 0.058)   # 手柄：(起点, 终点, 半宽)
CHECK      = ((0.335, 0.435), (0.408, 0.512), (0.560, 0.330), 0.038)  # 对勾：(A, B, C, 半宽)

SS = 4                        # 超采样倍数（抗锯齿）


# ── 几何判定 ──────────────────────────────────────────────
def in_rounded_rect(x, y, r):
    """点是否落在铺满画布、带圆角的方块内。"""
    cx = min(max(x, r), 1.0 - r)
    cy = min(max(y, r), 1.0 - r)
    if x == cx and y == cy:          # 落在中心矩形区域
        return True
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def in_ring(x, y, c, r_out, r_in):
    d2 = (x - c[0]) ** 2 + (y - c[1]) ** 2
    return r_in * r_in <= d2 <= r_out * r_out


def dist_to_segment(x, y, p, q):
    px, py = x - p[0], y - p[1]
    qx, qy = q[0] - p[0], q[1] - p[1]
    L2 = qx * qx + qy * qy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (px * qx + py * qy) / L2))
    dx, dy = px - t * qx, py - t * qy
    return (dx * dx + dy * dy) ** 0.5


def in_polyline(x, y, pts, half_w):
    """点到折线（含圆头）的距离 <= half_w 即算命中。"""
    for i in range(len(pts) - 1):
        if dist_to_segment(x, y, pts[i], pts[i + 1]) <= half_w:
            return True
    return False


# ── 渲染 ──────────────────────────────────────────────────
def render(size):
    """返回 RGBA 行数据。内部按 size*SS 采样后降采样，得到平滑边缘。"""
    n = size * SS
    step = 1.0 / n
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            acc = [0, 0, 0, 0]       # r, g, b(预乘), a
            for sy in range(SS):
                y = (py * SS + sy + 0.5) * step
                for sx in range(SS):
                    x = (px * SS + sx + 0.5) * step
                    if not in_rounded_rect(x, y, CORNER_R):
                        continue
                    # 底色
                    col = BG
                    # 放大镜环 + 手柄（白）
                    if in_ring(x, y, LENS_C, LENS_R_OUT, LENS_R_IN) or \
                       in_polyline(x, y, HANDLE[:2], HANDLE[2]):
                        col = WHITE
                    # 镜片内的对勾（绿）—— 后画，覆盖在环之上
                    if in_polyline(x, y, CHECK[:3], CHECK[3]):
                        col = GREEN
                    acc[0] += col[0]
                    acc[1] += col[1]
                    acc[2] += col[2]
                    acc[3] += 255
            total = SS * SS
            a = acc[3] // total
            if a == 0:
                row += bytes((0, 0, 0, 0))
            else:
                # 按实际覆盖的采样数求平均色（未被覆盖的采样不参与，避免边缘发暗）
                cov = acc[3] // 255
                row += bytes((acc[0] // cov, acc[1] // cov, acc[2] // cov, a))
        rows.append(bytes(row))
    return rows


def write_png(path, size, rows):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)   # 8bit RGBA
    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", ihdr) +
           chunk(b"IDAT", zlib.compress(raw, 9)) +
           chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    # Windows 控制台默认 GBK，打不出中文，强制 UTF-8
    try:
        import sys as _sys
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "extension", "icons")
    os.makedirs(out_dir, exist_ok=True)

    for size in (16, 32, 48, 128):
        rows = render(size)
        path = os.path.join(out_dir, "icon%d.png" % size)
        write_png(path, size, rows)
        print("  %-28s %d x %d  %d bytes" % (
            os.path.relpath(path, os.path.dirname(here)), size, size,
            os.path.getsize(path)))

    print("\n图标已生成到 extension/icons/")


if __name__ == "__main__":
    main()
