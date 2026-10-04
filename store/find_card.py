#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验真 · 截图定位工具
===================
全屏截图里找出「验真」卡片的位置。

思路：卡片的判定文字有固定颜色（来源 extension/content.js 的 BADGE 表）：
    🟢 可信      #16a34a
    🔴 与事实不符 #dc2626
    🟠 部分属实   #ea580c   ← 本次截图是这条
    🟡 证据不足   #d97706
这些颜色在普通网页上几乎不会出现，所以能精准定位卡片。

纯标准库：自己解码 PNG（不做依赖安装）。

用法：
    python store/find_card.py <截图路径>
"""

import os
import struct
import sys
import zlib

# 判定色（来自 content.js 的 BADGE 表）
BADGE_COLORS = {
    "supported":    ("🟢 可信",       (0x16, 0xa3, 0x4a)),
    "refuted":      ("🔴 与事实不符", (0xdc, 0x26, 0x26)),
    "mixed":        ("🟠 部分属实",   (0xea, 0x58, 0x0c)),
    "insufficient": ("🟡 证据不足",   (0xd9, 0x77, 0x06)),
}


# ────────────────────────── PNG 解码 ──────────────────────────
def _unfilter(raw, width, height, bpp, stride):
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _y in range(height):
        ft = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out += line
        prev = line
    return out


def decode_png(path):
    """返回 (width, height, pixels) ；pixels 是 bytearray，每像素 3 字节 RGB。"""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG")
    pos = 8
    width = height = None
    bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            width, height, bit_depth, color_type, comp, filt, inter = \
                struct.unpack(">IIBBBBB", body)
            if bit_depth != 8 or inter != 0 or color_type not in (2, 6):
                raise ValueError("只支持 8bit 非隔行的 RGB/RGBA PNG（本图是 "
                                 "depth=%s type=%s interlace=%s）"
                                 % (bit_depth, color_type, inter))
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break

    raw = zlib.decompress(bytes(idat))
    ch = 3 if color_type == 2 else 4
    stride = width * ch
    flat = _unfilter(raw, width, height, ch, stride)
    if ch == 3:
        return width, height, bytearray(flat)
    # RGBA → RGB
    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        rgb[i * 3:i * 3 + 3] = flat[i * 4:i * 4 + 3]
    return width, height, rgb


# ────────────────────────── 找颜色 ──────────────────────────
def clusters_of_color(px, w, h, target, tol=22, cell=48, min_cell=6):
    """找出某颜色的「密集色块」。

    全图包围盒没用 —— 一条判定色的文字只有几百个像素，但散落在全图的
    抗锯齿像素会把它撑成整张图。所以按网格分箱，再找连成一片的密集区域。
    """
    tr, tg, tb = target
    bins = {}
    for y in range(h):
        row = y * w * 3
        cy = y // cell
        for x in range(w):
            i = row + x * 3
            r, g, b = px[i], px[i + 1], px[i + 2]
            if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
                k = (x // cell, cy)
                e = bins.get(k)
                if e is None:
                    bins[k] = [1, x, y, x, y]
                else:
                    e[0] += 1
                    if x < e[1]: e[1] = x
                    if y < e[2]: e[2] = y
                    if x > e[3]: e[3] = x
                    if y > e[4]: e[4] = y

    dense = {k: v for k, v in bins.items() if v[0] >= min_cell}
    if not dense:
        return []

    # 把相邻的密集格子连成一片
    seen = set()
    out = []
    for k in sorted(dense, key=lambda k: -dense[k][0]):
        if k in seen:
            continue
        stack = [k]
        seen.add(k)
        total = 0
        x0, y0, x1, y1 = w, h, -1, -1
        while stack:
            cur = stack.pop()
            n, ax, ay, bx, by = dense[cur]
            total += n
            x0, y0 = min(x0, ax), min(y0, ay)
            x1, y1 = max(x1, bx), max(y1, by)
            cx, cy = cur
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nk = (cx + dx, cy + dy)
                    if nk in dense and nk not in seen:
                        seen.add(nk)
                        stack.append(nk)
        out.append((total, x0, y0, x1, y1))
    out.sort(reverse=True)
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if len(sys.argv) < 2:
        sys.exit("用法: python store/find_card.py <截图路径>")
    path = sys.argv[1]
    print("读取：%s" % path)

    w, h, px = decode_png(path)
    print("尺寸：%d x %d" % (w, h))

    found = []
    for key, (label, rgb) in BADGE_COLORS.items():
        cl = clusters_of_color(px, w, h, rgb)
        if cl:
            total, x0, y0, x1, y1 = cl[0]
            found.append((total, key, label, x0, y0, x1, y1))
            print("\n命中 %s  #%02x%02x%02x   （共 %d 个色块）"
                  % (label, *rgb, len(cl)))
            for i, (n, ax, ay, bx, by) in enumerate(cl[:3]):
                print("   #%d 像素 %-6d x %d..%d  y %d..%d  (%dx%d)"
                      % (i + 1, n, ax, bx, ay, by, bx - ax + 1, by - ay + 1))
    if not found:
        print("\n没找到任何判定色的密集色块。可能原因：截图被颜色管理改过、"
              "被大幅缩放、或卡片不在图里。")
        sys.exit(1)

    found.sort(reverse=True)
    n, key, label, x0, y0, x1, y1 = found[0]
    print("\n" + "=" * 56)
    print("判定文字：%s" % label)
    print("位置：x %d..%d  y %d..%d   （%d 像素）"
          % (x0, x1, y0, y1, n))
    # 判定色是给「emoji + 文字」上色，文字左边还有个彩色圆点，
    # 所以卡片左边界要往左让出一点；右边界同理。
    pad_x = 40
    print("\n卡片估计范围（判定行位于卡片上部，标题栏在其上方约 40px）：")
    print("  左 ≈ %d" % max(0, x0 - pad_x))
    print("  右 ≈ %d  （卡片宽 380 逻辑像素，本图缩放未知，先按判定文字宽度推）"
          % min(w - 1, x1 + pad_x))
    print("  上 ≈ %d" % max(0, y0 - 70))
    print("  下 = 未知，看内容多少")
    print("\n本次截图可能的缩放比：判定文字实测宽 %d px。若卡片是 380 逻辑像素宽，"
          % (x1 - x0 + 1))
    print("  则 1 逻辑像素 ≈ %.2f 物理像素" % ((x1 - x0 + 1) / 220.0))
    print("=" * 56)


if __name__ == "__main__":
    main()
