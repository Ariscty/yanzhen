#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验真 · 公开仓库前的密钥泄露自检
================================
**把仓库设为 public 之前跑一次。** 一旦密钥进了公开仓库的历史，
删掉文件也没用 —— 得重写历史或直接作废密钥。

本机常常没有 git 命令，所以这里直接读 .git 的内部结构，不依赖 git：
  · .git/index        → 当前被跟踪的文件（.env 在里面就危险）
  · .git/objects/**   → 所有对象（松散对象 + packfile），zlib 解压后搜密钥特征

用法：
    python store/check_secrets.py
退出码 0 = 干净，1 = 发现问题
"""

import os
import re
import sys
import struct
import zlib

# 通用密钥特征：只在「看出来是一个真的密钥值」时才命中。
# ⚠️ 不要把变量名（DEEPSEEK_API_KEY）本身当命中 —— 它本来就该出现在文档和
#    config.example.env 里，那样报出来全是误报，工具就没用了。
PATTERNS = [
    (re.compile(rb"sk-[A-Za-z0-9]{16,}"), "疑似 OpenAI / DeepSeek 风格的密钥（sk-…）"),
    (re.compile(rb"tvly-[A-Za-z0-9]{10,}"), "疑似 Tavily 密钥（tvly-…）"),
]

# 「变量名 = 真实值」这种赋值才算命中（键名本身不算）
ASSIGN = re.compile(
    rb"(?:DEEPSEEK|TAVILY|BOCHA)_API_KEY\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{20,})")

# 占位符白名单：这些出现在示例里是正常的
# （注意：bytes 字面量只能放 ASCII，中文占位符靠下面的 any() 判断处理不了，
#   但中文的"填你的key"这类值长度和字符集本来就过不了 ASSIGN 的正则）
PLACEHOLDERS = (b"your", b"xxx", b"placeholder", b"here", b"replace",
                b"example", b"none", b"changeme")

# 这些文件名出现在「已跟踪」列表里就算危险
RISKY_NAMES = (".env", ".env.local", ".env.production")


def read_index_paths(git_dir):
    """解析 .git/index 的二进制格式，取出被跟踪的文件路径。"""
    p = os.path.join(git_dir, "index")
    if not os.path.isfile(p):
        return None
    data = open(p, "rb").read()
    if data[:4] != b"DIRC":
        return None
    version, count = struct.unpack(">II", data[4:12])
    off = 12
    names = []
    for _ in range(count):
        if off + 62 > len(data):
            break
        name_len = struct.unpack(">H", data[off + 60:off + 62])[0]
        name = data[off + 62:off + 62 + name_len]
        names.append(name.decode("utf-8", "replace"))
        entry_len = 62 + name_len
        entry_len += (8 - (entry_len % 8)) or 8      # 补齐到 8 字节的倍数
        off += entry_len
    return names


def inflate_streams(blob):
    """把一段字节里所有能解开来的 zlib 流都解出来（够用来找密钥了）。"""
    out = []
    i = 0
    n = len(blob)
    while i < n - 2:
        if blob[i] == 0x78 and blob[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                d = zlib.decompressobj()
                chunk = d.decompress(blob[i:], 8 * 1024 * 1024)
                if chunk:
                    out.append(chunk)
                i += 512
                continue
            except Exception:
                pass
        i += 1
    return out


def scan_blobs(blobs, label):
    hits = []
    for raw in blobs:
        for rx, desc in PATTERNS:
            for m in rx.finditer(raw):
                # 只留前 6 位，别把密钥原文打进日志
                sample = m.group(0)[:6].decode("utf-8", "replace")
                hits.append((label, desc, sample + "…"))
        for m in ASSIGN.finditer(raw):
            val = m.group(1).lower()
            if any(p in val for p in PLACEHOLDERS):
                continue                      # 占位符，正常
            sample = m.group(1)[:6].decode("utf-8", "replace")
            hits.append((label, "「变量名 = 看起来是真值」的赋值", sample + "…"))
    return hits


def real_secrets(root):
    """读 .env，取出里面真正的密钥值 —— 这是最靠谱的比对依据。

    只认名字里带 KEY / TOKEN / SECRET / PASSWORD 的项。
    否则 DEEPSEEK_MODEL=deepseek-flash 这种公开信息也会被当成密钥，
    报出一堆假的"泄露"，把真问题淹掉。
    """
    p = os.path.join(root, ".env")
    if not os.path.isfile(p):
        return []
    looks_secret = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
    out = []
    for line in open(p, encoding="utf-8-sig", errors="replace").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if looks_secret.search(k) and len(v) >= 12:
            out.append((k, v))
    return out


def scan_exact(blobs, secrets):
    """拿真实密钥逐字节比对 —— 命中就是真的泄露，没有误报。"""
    hits = []
    for key, val in secrets:
        needle = val.encode("utf-8")
        n = sum(1 for raw in blobs if needle in raw)
        if n:
            hits.append((key, val[:6], n))
    return hits


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    git_dir = os.path.join(root, ".git")

    print("检查目录：%s\n" % root)

    if not os.path.isdir(git_dir):
        sys.exit("不是 git 仓库（没有 .git），无需检查。")

    problems = []

    # ── 1. 当前被跟踪的文件 ────────────────────────────────
    print("【1】被跟踪的文件")
    names = read_index_paths(git_dir)
    if names is None:
        print("  ? 读不出 .git/index（格式不认识），跳过")
    else:
        print("  共 %d 个文件被 git 跟踪" % len(names))
        bad = [n for n in names if os.path.basename(n) in RISKY_NAMES]
        if bad:
            for n in bad:
                print("  ✗ 危险：%s 正被跟踪 —— 设为 public 后任何人可下载！" % n)
                problems.append("被跟踪的密钥文件：" + n)
        else:
            print("  ✓ 没有 .env 之类的密钥文件被跟踪")

    # ── 2. git 对象里的内容 ───────────────────────────────
    print("\n【2】git 对象内容（含历史提交）")
    blobs = []
    obj_dir = os.path.join(git_dir, "objects")
    loose = 0
    pack_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(obj_dir):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            data = open(fp, "rb").read()
            if fn.endswith(".pack"):
                pack_bytes += len(data)
                blobs.extend(inflate_streams(data))
            elif len(fn) == 38 and not fn.endswith(".idx"):     # 松散对象
                loose += 1
                try:
                    blobs.append(zlib.decompress(data))
                except Exception:
                    blobs.append(data)
    print("  松散对象 %d 个，packfile %d 字节 → 解出 %d 段内容" % (loose, pack_bytes, len(blobs)))

    hits = scan_blobs(blobs, "objects")
    if hits:
        for label, desc, sample in hits:
            print("  ✗ 命中：%s（%s）" % (desc, sample))
            problems.append("git 对象里发现：" + desc)
    else:
        print("  ✓ 所有对象里都没有密钥特征")

    # ── 2b. 拿 .env 里的真实密钥逐字节比对（最硬的证据）─────
    print("\n【2b】用 .env 里的真实密钥比对 git 对象（无误报）")
    secrets = real_secrets(root)
    if not secrets:
        print("  — 没读到 .env 里的有效密钥，跳过逐字节比对")
    else:
        print("  从 .env 读到 %d 条密钥（只显示前 6 位）：" % len(secrets))
        for k, v in secrets:
            print("    %s = %s…（长度 %d）" % (k, v[:6], len(v)))
        exact = scan_exact(blobs, secrets)
        if exact:
            for key, prefix, n in exact:
                print("  ✗ 严重：%s 的真实值出现在 %d 段 git 对象里！" % (key, n))
                problems.append("%s 的真实密钥值已进入 git 历史" % key)
        else:
            print("  ✓ 没有任何一条真实密钥出现在 git 对象里 —— 干干净净")

    # ── 3. 工作区里除了 .env 还有没有别的 ──────────────────
    print("\n【3】工作区文件")
    print("  在 ." + "gitignore 里的敏感文件（正常，不会进仓库）：")
    for n in RISKY_NAMES:
        fp = os.path.join(root, n)
        if os.path.isfile(fp):
            gi = open(os.path.join(root, ".gitignore"), encoding="utf-8").read() \
                if os.path.isfile(os.path.join(root, ".gitignore")) else ""
            ignored = n in gi
            print("    %s %s %s" % ("✓" if ignored else "✗", n,
                                   "(已被 .gitignore 忽略)" if ignored else "**没被忽略！**"))
            if not ignored:
                problems.append(n + " 没有被 .gitignore 忽略")

    # ── 结论 ───────────────────────────────────────────────
    print("\n" + "=" * 62)
    if problems:
        print("⚠️  发现 %d 个问题，**先别把仓库设成 public**：" % len(problems))
        for p in problems:
            print("   · " + p)
        print("\n如果密钥确实进过历史：删文件没用，要么 `git filter-repo` 重写历史，")
        print("要么直接去各家控制台把旧密钥作废、换个新的。后者更省事也更快。")
        sys.exit(1)
    print("✅ 干净。可以放心把仓库设为 public。")
    print("=" * 62)


if __name__ == "__main__":
    main()
