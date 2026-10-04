#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验真 · 商店打包脚本
===================
把 extension/ 打包成可直接上传商店的 zip。

商店的硬要求（踩过一次就白等一周）：
  1. **manifest.json 必须在 zip 的最外层**，不能再套一层 yanzhen/ 文件夹
  2. manifest 里必须有 128x128 的 icons
  3. 不能夹带 .env、key、缓存等任何私密文件

本脚本会先自检再打包，任何一项不通过就拒绝出包（而不是让你提交后被拒）。

用法：
    python store/pack.py
输出：
    dist/yanzhen-<version>.zip
"""

import json
import os
import sys
import zipfile

# ── 绝对不允许进入发布包的路径片段 ──────────────────────────
FORBIDDEN = (".env", ".git", "node_modules", "__pycache__", ".DS_Store", ".map")
FORBIDDEN_EXT = (".log", ".pem", ".key")


def fail(msg):
    print("  ✗ " + msg)
    return False


def main():
    # Windows 控制台默认 GBK，打不出 ✓/✗ 和中文，强制 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ext = os.path.join(root, "extension")

    if not os.path.isdir(ext):
        sys.exit("找不到 extension 目录：" + ext)

    # ── 自检 ────────────────────────────────────────────────
    print("自检：")
    ok = True

    mf_path = os.path.join(ext, "manifest.json")
    if not os.path.isfile(mf_path):
        sys.exit(fail("extension/manifest.json 不存在，无法打包"))
    try:
        mf = json.load(open(mf_path, encoding="utf-8"))
    except Exception as e:
        sys.exit(fail("manifest.json 不是合法 JSON：%s" % e))
    print("  ✓ manifest.json 合法（name=%s, version=%s）" % (mf.get("name"), mf.get("version")))

    # 图标
    icons = mf.get("icons", {})
    if "128" not in icons:
        ok = fail("manifest 缺少 128x128 图标，商店会拒绝")
    for size, rel in sorted(icons.items()):
        p = os.path.join(ext, rel)
        if not os.path.isfile(p):
            ok = fail("图标文件不存在：%s" % rel)
    if ok:
        print("  ✓ 图标齐全：%s" % ", ".join(sorted(icons.keys(), key=int)))

    # 版本号
    ver = mf.get("version", "0.0.0")

    # 收集文件
    files = []
    for dirpath, dirnames, filenames in os.walk(ext):
        dirnames[:] = [d for d in dirnames if d not in FORBIDDEN]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ext).replace("\\", "/")
            low = rel.lower()
            if any(f in low for f in FORBIDDEN) or low.endswith(FORBIDDEN_EXT):
                ok = fail("发现不该进包的文件：%s" % rel)
                continue
            files.append((full, rel))

    if not files:
        sys.exit(fail("extension 目录是空的"))
    print("  ✓ 待打包 %d 个文件" % len(files))

    if not ok:
        sys.exit("\n自检未通过，不出包。")

    # ── 打包 ────────────────────────────────────────────────
    dist = os.path.join(root, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, "yanzhen-%s.zip" % ver)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in sorted(files, key=lambda x: x[1]):
            z.write(full, rel)          # ← arcname=rel，保证 manifest 在最外层

    # ── 校验产物 ────────────────────────────────────────────
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        if "manifest.json" not in names:
            sys.exit(fail("打包结果里 manifest.json 不在最外层，商店会拒绝"))

    print("\n出包成功：")
    print("  %s" % os.path.relpath(out, root))
    print("  %d 个文件，%d bytes" % (len(names), os.path.getsize(out)))
    print("\n包内清单：")
    for n in sorted(names):
        print("    " + n)
    print("\n下一步：见 store/SUBMIT.md")


if __name__ == "__main__":
    main()
