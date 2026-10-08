#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配对对比两臂评测结果：全文抓取「开」vs「关」。

为什么要配对，而不是比两个总分？
    这个项目自己记录过：19 条样本 + 单次运行，噪声下限约 ±1 条（见 eval/NOTES.md）。
    只比"73.7% vs 78.9%"说明不了任何事。配对做的是另一件事：
    **同一条样本在两臂下判成了什么**，以及翻转能不能归因到"看到正文"这个机制上。

设计上两臂是受控的：
    断言（cache_claims）、检索结果（cache_search）全部走缓存，两臂完全一致，
    唯一变量就是 check.py 里有没有调 fetch.enrich()。所以任何逐条差异都只能来自
    证据正文，而不是"这次搜到的网页不一样"。

用法：
    python eval/compare_arms.py eval/RESULT-fulltext-ON.partial.json eval/RESULT-fulltext-OFF.partial.json
"""
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LABEL = {"supported": "可信", "refuted": "不符",
         "insufficient": "不足", "mixed": "混合"}


def load(path):
    p = pathlib.Path(path)
    rows = json.loads(p.read_text(encoding="utf-8"))
    return {r["id"]: r for r in rows}


def acc(rows):
    n = len(rows)
    c = sum(1 for r in rows.values() if r.get("ok"))
    return c, n, (c / n * 100 if n else 0)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    a_on, a_off = load(sys.argv[1]), load(sys.argv[2])
    ids = [i for i in a_on if i in a_off]
    if not ids:
        print("两臂没有共同样本。")
        return 1

    on = {i: a_on[i] for i in ids}
    off = {i: a_off[i] for i in ids}
    c_on, n, p_on = acc(on)
    c_off, _, p_off = acc(off)

    print("=" * 72)
    print("配对对比：FULLTEXT 开 vs 关（同断言、同检索结果，唯一变量=有没有抓正文）")
    print("=" * 72)
    print("  全文抓取【开】：%d/%d = %.1f%%" % (c_on, n, p_on))
    print("  全文抓取【关】：%d/%d = %.1f%%" % (c_off, n, p_off))
    print("  差值：%+d 条" % (c_on - c_off))

    dose_n = sum(r.get("fulltext_n") or 0 for r in on.values())
    dose_ev = sum(r.get("ev_n") or 0 for r in on.values())
    dose_ch = sum(r.get("ev_chars") or 0 for r in on.values())
    ch_off = sum(r.get("ev_chars") or 0 for r in off.values())
    print("  治疗剂量：开这一臂抓到 %d / %d 条证据的正文，正文合计 %d 字"
          % (dose_n, dose_ev, dose_ch))
    print("  对照：关这一臂证据正文合计 %d 字（只多 %.0f 字）"
          % (ch_off, dose_ch - ch_off))

    tok_on = sum(r.get("tokens") or 0 for r in on.values())
    tok_off = sum(r.get("tokens") or 0 for r in off.values())
    print("  token：开 %d，关 %d（+%.0f%%）"
          % (tok_on, tok_off, (tok_on - tok_off) / tok_off * 100 if tok_off else 0))

    print()
    print("─" * 72)
    print("逐条对照（只列两臂不同的）")
    print("─" * 72)
    changed = [i for i in ids if on[i].get("got") != off[i].get("got")]
    if not changed:
        print("  两臂**逐条完全相同** —— 全文抓取没有改变任何一条判定。")
        print("  （这不等于它没用：可能是证据本来就不缺，也可能是抓到的正文没被用上。）")
    for i in changed:
        o, f = on[i], off[i]
        better = "✅ 开更好" if o.get("ok") and not f.get("ok") else (
            "❌ 开更差" if f.get("ok") and not o.get("ok") else "➖ 都不对/都对")
        print()
        print("  %s  期望「%s」  %s" % (i, LABEL.get(o["expected"], o["expected"]), better))
        print("    关 → %s   开 → %s" % (LABEL.get(f.get("got")), LABEL.get(o.get("got"))))
        print("    治疗剂量：%d/%d 条证据取到正文"
              % (o.get("fulltext_n") or 0, o.get("ev_n") or 0))
        print("    原文：%s" % (o.get("text") or "")[:80])
        for tag, r in (("关", f), ("开", o)):
            print("    [%s] 逐条：" % tag)
            for res in r.get("results") or []:
                print("        · %s → %s：%s"
                      % (res.get("claim", "")[:34],
                         LABEL.get(res.get("verdict"), res.get("verdict")),
                         (res.get("reason") or "")[:96]))

    print()
    print("─" * 72)
    print("整体逐条表")
    print("─" * 72)
    print("  %-5s %-6s %-6s %-6s %-6s %s" % ("id", "期望", "开", "关", "变化", "全文/证据"))
    for i in ids:
        o, f = on[i], off[i]
        mark = ""
        if o.get("got") != f.get("got"):
            mark = "← 翻转"
        print("  %-5s %-6s %-6s %-6s %-6s %d/%d"
              % (i, LABEL.get(o["expected"], o["expected"]),
                 LABEL.get(o.get("got"), o.get("got")),
                 LABEL.get(f.get("got"), f.get("got")), mark,
                 o.get("fulltext_n") or 0, o.get("ev_n") or 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
