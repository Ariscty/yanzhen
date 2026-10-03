#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验真 (YanZhen) — 划词事实核查工具 · 命令行原型

用法：
    python yanzhen.py "要核查的一段文字"
    python yanzhen.py                  # 交互式：粘贴文字，然后单独一行输入 END
    python yanzhen.py --mock "文字"     # 用模拟搜索跑通流程（不花搜索额度）
    python yanzhen.py -f 文件.txt       # 从文件读
    python yanzhen.py --no-color "文字" # 关掉颜色
    python yanzhen.py --debug "文字"    # 额外打印每条断言用到的原始证据

只用 Python 标准库，不需要 pip install 任何东西。
"""
import argparse
import sys
import time

import check
import config
import llm
import search
import sources

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CODES = {"red": "91", "green": "92", "yellow": "93",
         "cyan": "96", "dim": "2", "bold": "1"}
BADGE = {
    "supported":    ("🟢", "可信", "green"),
    "refuted":      ("🔴", "与事实不符", "red"),
    "insufficient": ("🟡", "证据不足", "yellow"),
    "mixed":        ("🟠", "部分属实", "yellow"),
}
NUM = "①②③④⑤⑥⑦⑧⑨"


def paint(text, color, enabled):
    if not enabled or color not in CODES:
        return text
    return "\033[%sm%s\033[0m" % (CODES[color], text)


def rule(char="─", width=60, enabled=True):
    print(paint(char * width, "dim", enabled))


def read_input(args):
    if args.file:
        with open(args.file, encoding="utf-8-sig") as f:
            return f.read().strip()
    if args.text:
        return " ".join(args.text).strip()
    print("粘贴要核查的文字（可以多行），最后单独一行输入 END 回车：")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def render(claims, results, overall, usages, elapsed, provider, color, debug=False):
    print()
    rule(enabled=color)
    icon, label, c = BADGE.get(overall, BADGE["insufficient"])
    extra = ""
    if len(results) > 1:
        hits = sum(1 for r in results if r.get("verdict") == "refuted")
        if hits:
            extra = "（%d 条断言中 %d 条与事实不符）" % (len(results), hits)
    print("  " + paint("结论：%s %s" % (icon, label), c, color) + extra)
    rule(enabled=color)

    for i, r in enumerate(results):
        v = r.get("verdict", "insufficient")
        icon, label, c = BADGE.get(v, BADGE["insufficient"])
        mark = NUM[i] if i < len(NUM) else "%d)" % (i + 1)
        claim = r.get("claim") or (claims[i]["claim"] if i < len(claims) else "")
        print("\n%s %s" % (paint(mark, "bold", color), claim))
        print("   %s %s   置信度 %.0f%%"
              % (paint(icon, c, color), paint("[" + label + "]", c, color),
                 (r.get("confidence") or 0) * 100))
        print("   理由：%s" % (r.get("reason") or "（模型没给理由）"))

        votes = r.get("votes") or {}
        if sum(votes.values()) > 1:
            detail = "  ".join("%s×%d" % (check.VERDICT_LABEL.get(k, k), v)
                               for k, v in sorted(votes.items()))
            print("   多次核查：%s" % detail)

        # 判定实际依据：显示「被引用的来源」的等级分布，而不是本断言检索到的全部证据。
        # 同一段话里，为断言①检索到的辟谣文章往往也能支撑断言③，跨断言引用是正常的，
        # 所以这里按实际引用来统计，避免出现"无 A/B 级来源"的误导性警告。
        cited = r.get("sources") or []
        cited_tiers = sources.tiers_of_urls([s.get("url", "") for s in cited])
        ev = claims[i].get("evidence", []) if i < len(claims) else []
        if cited:
            strong = sources.has_strong_tiers(cited_tiers)
            flag = "" if strong else paint("  ← 引用来源里没有 A/B 级", "yellow", color)
            print("   引用来源：%s%s" % (sources.summary_tiers(cited_tiers), flag))
        else:
            print("   " + paint("引用来源：（模型未引用任何来源，请谨慎采信）", "yellow", color))
        if ev:
            print(paint("   （本断言共检索到 %d 条证据）" % len(ev), "dim", color))

        for s in cited[:5]:
            lvl, _ = sources.tier_of(s.get("url", ""))
            tag = lvl.split()[0] if lvl != sources.UNKNOWN else "?"
            print("     · [%s] %s  %s"
                  % (tag, (s.get("title") or "")[:38], s.get("url") or ""))

        dropped = r.get("dropped_sources") or []
        if dropped:
            print("   " + paint(
                "⚠️ 已剔除 %d 条模型编造的来源（不在检索结果里）：%s"
                % (len(dropped), ", ".join((d.get("url") or "")[:40] for d in dropped)),
                "yellow", color))

        if debug:
            for e in ev:
                print(paint("      [原始证据][%s] %s" % (e.get("tier"), e.get("url")),
                            "dim", color))

    total = check.summarize_usage(usages)
    print()
    rule(enabled=color)
    print(paint("  搜索来源：%s   ·   耗时 %.1f 秒   ·   token 合计 %d"
                % (provider, elapsed, total["total_tokens"]), "dim", color))
    if provider == "mock":
        print(paint("  ⚠️ 本次用的是【模拟搜索】，证据是假的，结论不可当真，仅用于验证流程。",
                    "yellow", color))
    print(paint("  本工具只做辅助参考，不构成事实认定。", "dim", color))
    rule(enabled=color)


def main():
    ap = argparse.ArgumentParser(description="验真 — 划词事实核查（命令行原型）")
    ap.add_argument("text", nargs="*", help="要核查的文字")
    ap.add_argument("-f", "--file", help="从文本文件读取")
    ap.add_argument("--mock", action="store_true", help="用模拟搜索，不联网检索")
    ap.add_argument("--no-color", action="store_true", help="不要彩色输出")
    ap.add_argument("--debug", action="store_true", help="打印原始证据")
    ap.add_argument("--votes", type=int, default=0,
                    help="判定跑几次取多数（覆盖 .env 里的 JUDGE_VOTES，如 3）")
    args = ap.parse_args()

    cfg = config.load()
    if args.mock:
        cfg["SEARCH_PROVIDER"] = "mock"
    if args.votes:
        cfg["JUDGE_VOTES"] = str(args.votes)

    problems = config.check_keys(cfg)
    if problems:
        print("配置有问题：")
        for p in problems:
            print("  · " + p)
        print("\n提示：把 config.example.env 复制成 .env，填好 key 再运行。")
        return 2

    text = read_input(args)
    if not text:
        print("没有输入内容。")
        return 2

    color = not args.no_color and sys.stdout.isatty()
    t0 = time.time()

    def progress(stage, info=""):
        if stage == "split":
            print(paint("[1/3] 正在拆分断言…", "dim", color))
        elif stage == "search":
            print(paint("[2/3] 正在检索证据…", "dim", color))
        elif stage == "searching":
            print("      · " + (info or "")[:40])
        elif stage == "judge":
            print(paint("[3/3] 正在基于证据判定…", "dim", color))
        elif stage == "cache_hit":
            print(paint("（命中结果缓存：这段文字查过，直接复用上次结论，不花钱）", "dim", color))

    try:
        claims, results, usages = check.run(cfg, text, on_progress=progress)
    except llm.LLMError as e:
        print("\n模型调用失败：" + str(e))
        return 1
    except search.SearchError as e:
        print("\n搜索失败：" + str(e))
        return 1
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130

    if not claims:
        print("\n这段话里没有找到可以核查的事实性断言（可能全是观点或情绪表达）。")
        return 0

    render(claims, results, check.overall_verdict(results), usages,
           time.time() - t0, cfg.get("SEARCH_PROVIDER"), color, args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
