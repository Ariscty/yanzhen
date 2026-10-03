#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测脚本：跑 eval/cases.json 里的样本，算出准确率。

用法：
    python eval/run_eval.py                  # 跑全部
    python eval/run_eval.py --limit 5        # 只跑前 5 条（省钱）
    python eval/run_eval.py --only r01 t01   # 只跑指定 id
    python eval/run_eval.py --provider mock  # 用模拟搜索（不算真实准确率，只验证脚本）

产出：终端表格 + eval/RESULT.md 报告
注意：每条样本约消耗 1 万 token，跑 20 条约 20 万 token，先想清楚再跑全量。
"""
import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # 让脚本能 import 到上一层的模块

# Windows 终端的中文/emoji 输出保险（GBK 控制台编不出 ✅ 这类字符）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import check          # noqa: E402
import config         # noqa: E402
import llm            # noqa: E402
import search         # noqa: E402
import sources        # noqa: E402

CASES = HERE / "cases.json"
REPORT = HERE / "RESULT.md"
LABEL = {"supported": "可信", "refuted": "不符",
         "insufficient": "不足", "mixed": "混合"}


def load_cases(path):
    if not path.exists():
        print("没找到 %s" % path)
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data.get("cases") or []


def run_one(cfg, case):
    """跑一条样本，返回 (got, results, error, usage_total, elapsed)。

    任何异常都不往外抛 —— 19 条样本跑到第 15 条才崩、白花 14 条的钱，
    这种事不该发生。
    """
    t0 = time.time()
    try:
        claims, results, usages = check.run(cfg, case["text"])
    except Exception as e:
        return None, [], "%s: %s" % (type(e).__name__, e), 0, time.time() - t0
    if not claims:
        return "insufficient", [], "没有拆出可核查的断言", 0, time.time() - t0
    got = check.overall_verdict(results)
    usage = check.summarize_usage(usages)["total_tokens"]
    return got, results, None, usage, time.time() - t0


def dump_partial(rows, path):
    """每跑完一条就落盘，中途崩了也不至于全丢。"""
    try:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="验真 · 评测脚本")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    ap.add_argument("--only", nargs="*", default=[], help="只跑指定 id")
    ap.add_argument("--provider", help="临时覆盖 SEARCH_PROVIDER")
    ap.add_argument("--cases", default=str(CASES), help="样本文件路径")
    ap.add_argument("--report", default=str(REPORT), help="报告输出路径")
    ap.add_argument("--yes", action="store_true", help="跳过花费确认")
    ap.add_argument("--resume", action="store_true",
                    help="复用上次中断留下的 .partial.json，跳过已跑成功的样本")
    ap.add_argument("--redo", nargs="*", default=[],
                    help="配合 --resume：强制重跑这些 id（改判或代码改动后用）")
    args = ap.parse_args()

    cases_path = pathlib.Path(args.cases)
    report_path = pathlib.Path(args.report)
    cases = load_cases(cases_path)
    if not cases:
        return 2
    if args.only:
        cases = [c for c in cases if c.get("id") in args.only]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("筛选后没有样本。")
        return 2

    cfg = config.load()
    if args.provider:
        cfg["SEARCH_PROVIDER"] = args.provider
    problems = config.check_keys(cfg)
    if problems:
        for p in problems:
            print("· " + p)
        return 2

    print("准备跑 %d 条样本（每条约 1 万 token，总耗时约 %d 分钟）"
          % (len(cases), max(1, len(cases) * 15 // 60)))
    if not args.yes:
        ans = input("继续？输入 y 回车：").strip().lower()
        if ans != "y":
            print("已取消。")
            return 0

    rows = []
    correct = 0
    t_start = time.time()
    total_tokens = 0

    # --resume：复用上次中断前跑成功的样本，不重复花钱。
    # 出错的行不复用（要重跑）。
    partial_path = report_path.with_suffix(".partial.json")
    reuse = {}
    if args.resume and partial_path.exists():
        try:
            for r in json.loads(partial_path.read_text(encoding="utf-8")):
                if r.get("got") and not r.get("error"):
                    reuse[r.get("id")] = r
        except Exception as e:
            print("（读 .partial.json 失败，忽略：%s）" % e)
        if reuse:
            print("复用上次已跑成功的 %d 条：%s"
                  % (len(reuse), " ".join(sorted(reuse))))

    for i, case in enumerate(cases, 1):
        cid, exp = case.get("id", "?"), case.get("expected", "?")

        if cid in reuse and cid not in args.redo:
            r = reuse[cid]
            r["expected"] = exp
            r["ok"] = (r["got"] == exp)      # 期望值可能被改判过，必须重算
            rows.append(r)
            if r["ok"]:
                correct += 1
            total_tokens += r.get("tokens", 0)
            print("[%d/%d] %s ⏭ 复用上次结果（判成 %s）"
                  % (i, len(cases), cid, LABEL.get(r["got"], r["got"])))
            continue

        print("[%d/%d] %s（期望 %s）… " % (i, len(cases), cid, LABEL.get(exp, exp)),
              end="", flush=True)
        got, results, err, tokens, elapsed = run_one(cfg, case)
        total_tokens += tokens

        ok = (got == exp)
        if ok:
            correct += 1
        rows.append({
            "id": cid, "expected": exp, "got": got, "ok": ok,
            "error": err, "tokens": tokens, "elapsed": elapsed,
            "text": case.get("text", ""),
            "basis_url": case.get("basis_url", ""),
            "basis_source": case.get("basis_source", ""),
            "note": case.get("note", ""),
            "results": results,
        })
        if err:
            print("❌ 出错：%s" % err)
        else:
            print("%s 判成 %s（%.1fs）" % ("✅" if ok else "❌",
                                          LABEL.get(got, got), elapsed))
        dump_partial(rows, report_path.with_suffix(".partial.json"))

    acc = correct / len(cases) * 100 if cases else 0
    print("\n" + "=" * 56)
    print("准确率：%d/%d = %.1f%%" % (correct, len(cases), acc))
    print("总耗时 %.1f 分钟，总 token %d" % ((time.time() - t_start) / 60, total_tokens))
    print("=" * 56)

    write_report(rows, acc, total_tokens, cfg, report_path)
    print("详细报告已写入：%s" % report_path)
    return 0


def write_report(rows, acc, total_tokens, cfg, report_path):
    lines = ["# 验真 · 评测报告", ""]
    lines.append("- 样本数：%d" % len(rows))
    lines.append("- 准确率：**%.1f%%**" % acc)
    lines.append("- 总 token：%d" % total_tokens)
    lines.append("- 搜索来源：%s" % cfg.get("SEARCH_PROVIDER"))
    lines.append("")
    lines.append("## 逐条结果")
    lines.append("")
    lines.append("| id | 期望 | 实际 | 结果 | 耗时 |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append("| %s | %s | %s | %s | %.1fs |"
                     % (r["id"], LABEL.get(r["expected"], r["expected"]),
                        LABEL.get(r["got"], r["got"] or "出错"),
                        "✅" if r["ok"] else "❌", r["elapsed"]))

    wrong = [r for r in rows if not r["ok"]]
    lines += ["", "## 判错的样本（重点看这些）", ""]
    if not wrong:
        lines.append("没有判错的样本。")
    for r in wrong:
        lines += ["### %s：期望「%s」，实际「%s」" % (
            r["id"], LABEL.get(r["expected"], r["expected"]),
            LABEL.get(r["got"], r["got"] or "出错")), ""]
        lines.append("> 原文：%s" % r["text"])
        lines.append("")
        if r["error"]:
            lines.append("出错信息：`%s`" % r["error"])
            lines.append("")
        lines.append("依据来源（人工核对用）：%s" % r["basis_url"])
        lines.append("")
        for res in r["results"]:
            cited = [s.get("url", "") for s in (res.get("sources") or [])]
            tiers = sources.summary_tiers(sources.tiers_of_urls(cited)) if cited else "无引用"
            lines.append("- 断言「%s」→ **%s**（置信度 %.0f%%）：%s"
                         % (res["claim"], LABEL.get(res["verdict"], res["verdict"]),
                            res["confidence"] * 100, res["reason"]))
            lines.append("  - 引用来源等级：%s" % tiers)
        lines.append("")

    lines += ["", "## 判对的样本", ""]
    for r in rows:
        if r["ok"]:
            lines.append("- %s：%s" % (r["id"], r["text"][:50]))
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
