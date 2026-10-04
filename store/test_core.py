#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验真 · 内核离线测试
===================
在没有 Node.js 的机器上，借 Edge 的 JS 引擎把 extension/core.js 真跑一遍。

原理：core.js 是自包含的（没有 import，且刻意不碰任何浏览器 API），
      所以把它的 `export ` 前缀去掉就能直接内联进 <script> 里执行；
      用 Edge 无头模式 --dump-dom 把结果读回来。

覆盖的是最容易出错、又不需要联网/不需要花 API 钱的那几条纯逻辑：
  · tierOf          来源分级（A/B/C/D/当事方/未分级）
  · verifySources   引用校验硬闸门（模型编的网址必须被剔除）
  · overallVerdict  总判定优先级（refuted 必须压过 mixed —— 上次回归事故的核心）

用法：
    python store/test_core.py
"""

import os
import re
import subprocess
import sys
import tempfile

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# ── 测试用例 ────────────────────────────────────────────────
# 每条： (说明, 表达式, 期望值)   期望值 None = 只打印不判对错
TIER_CASES = [
    ("中国政府网",        "tierOf('https://www.gov.cn/zhengce/2024.htm')",        "A 官方一手"),
    ("WHO（国际组织）",   "tierOf('https://www.who.int/news/item/1')",            "A 官方一手"),
    ("英国政府",          "tierOf('https://www.gov.uk/government/news/1')",       "A 官方一手"),
    ("中国疾控中心",      "tierOf('https://www.chinacdc.cn/jkzt/1.html')",        "A 官方一手"),
    ("新华网",            "tierOf('https://www.xinhuanet.com/politics/1.htm')",   "B 权威媒体"),
    ("澎湃新闻",          "tierOf('https://www.thepaper.cn/newsDetail_1')",       "B 权威媒体"),
    ("OpenAI 官网",       "tierOf('https://openai.com/index/gpt')",               "A 当事方官网"),
    ("微软官网",          "tierOf('https://www.microsoft.com/zh-cn/1')",          "A 当事方官网"),
    ("微博",              "tierOf('https://weibo.com/1234567/abc')",              "D 自媒体百科"),
    ("知乎",              "tierOf('https://www.zhihu.com/question/123')",         "D 自媒体百科"),
    ("百度百科",          "tierOf('https://baike.baidu.com/item/x')",             "D 自媒体百科"),
    ("认不出来的域名",    "tierOf('https://some-random-blog.example/1')",         "未分级"),
    ("空 URL",            "tierOf('')",                                           "未分级"),
    ("不是 URL 的字符串", "tierOf('not a url')",                                  "未分级"),
    # 下面两条只看输出了什么，不预设答案（名单覆盖情况靠人眼核对）
    ("BBC",               "tierOf('https://www.bbc.com/news/1')",                 None),
    ("路透社",            "tierOf('https://www.reuters.com/world/1')",            None),
]

# 引用校验：results 里挂的 sources，只有真在 claims.evidence 里出现过的才准留下
VERIFY_JS = """
(() => {
  const results = [{ claim: 'c1', sources: [
      { url: 'https://www.gov.cn/a.htm',  title: '真来源' },
      { url: 'https://fake-hallucinated.com/x', title: '模型编的' },
      { url: '  https://www.xinhuanet.com/b.htm  ', title: '带空格的真来源' },
      { url: '', title: '空网址' },
  ]}];
  const claims = [{ text: 'c1', evidence: [
      { url: 'https://www.gov.cn/a.htm' },
      { url: 'https://www.xinhuanet.com/b.htm' },
  ]}];
  const out = verifySources(results, claims);
  return JSON.stringify({
      kept: out[0].sources.map(s => s.title),
      dropped: out[0].droppedSources.map(s => s.title),
  });
})()
"""

# 总判定优先级
VERDICT_CASES = [
    ("refuted 必须压过 mixed（回归事故的核心规则）", "['refuted','mixed']", "refuted"),
    ("refuted 压过 supported",                       "['supported','refuted']", "refuted"),
    ("mixed 压过 supported",                         "['mixed','supported']", "mixed"),
    ("全 supported 才是 supported",                  "['supported','supported']", "supported"),
    ("有 insufficient 且无否证 → insufficient",      "['supported','insufficient']", "insufficient"),
    ("空数组 → insufficient",                        "[]", "insufficient"),
]


def build_html(core_src, cases_js, syntax_js):
    return """<!DOCTYPE html><meta charset="utf-8"><pre id="out"></pre>
<script>
const R = [];
%s
// ---------------- 语法检查：另外三个 JS 文件 ----------------
// 用 new Function() 只解析不执行 —— 语法错一个，扩展就整个加载不了。
const SYNTAX = %s;
for (const f of SYNTAX) {
  try {
    new Function(f.code);
    R.push({g:'syntax', name:f.name, got:'语法 OK', want:'语法 OK'});
  } catch (e) {
    R.push({g:'syntax', name:f.name, got:'语法错误: ' + e.message, want:'语法 OK'});
  }
}
// ---------------- 功能测试 ----------------
%s
document.getElementById('out').textContent = '###RESULT###' + JSON.stringify(R) + '###END###';
</script>""" % (core_src, syntax_js, cases_js)


def make_cases_js():
    lines = []
    for name, expr, want in TIER_CASES:
        lines.append(
            "R.push({g:'tier', name:%r, got:tierLetter(%s[0]) + ' ' + (%s[1] ? '·' : ''), "
            "raw:%s[0], want:%r});" % (name, expr, expr, expr, want))
    # 上面那行拼起来可读性差，改用更直接的方式重写：
    lines = []
    for name, expr, want in TIER_CASES:
        lines.append(
            "try { const t = %s; R.push({g:'tier', name:%s, got:t[0], want:%s}); }"
            " catch (e) { R.push({g:'tier', name:%s, got:'抛异常: '+e.message, want:%s}); }"
            % (expr, js_str(name), js_str(want), js_str(name), js_str(want)))

    for name, expr, want in VERDICT_CASES:
        lines.append(
            "try { const v = overallVerdict(%s.map(x=>({verdict:x})));"
            " R.push({g:'verdict', name:%s, got:v, want:%s}); }"
            " catch (e) { R.push({g:'verdict', name:%s, got:'抛异常: '+e.message, want:%s}); }"
            % (expr, js_str(name), js_str(want), js_str(name), js_str(want)))

    lines.append(
        "try { const v = %s; R.push({g:'verify', name:'引用校验硬闸门', "
        "got:v, want:'KEEP'}); }"
        " catch (e) { R.push({g:'verify', name:'引用校验硬闸门', "
        "got:'抛异常: '+e.message, want:'KEEP'}); }" % VERIFY_JS)

    # 附加：分级汇总显示
    lines.append(
        "try { R.push({g:'extra', name:'tierSummary 汇总显示', got: tierSummary("
        "[TIER.A, TIER.P, TIER.B, TIER.B, TIER.D, TIER.U]), want:'A×2 B×2 D×1 ?×1'}); }"
        " catch(e){ R.push({g:'extra', name:'tierSummary', got:'抛异常: '+e.message, want:'A×2 B×2 D×1 ?×1'}); }")
    lines.append(
        "try { R.push({g:'extra', name:'hasStrongTiers(A,B)', got: String(hasStrongTiers([TIER.A,TIER.B])), want:'true'});"
        " R.push({g:'extra', name:'hasStrongTiers(C,D)', got: String(hasStrongTiers([TIER.C,TIER.D])), want:'false'}); }"
        " catch(e){ R.push({g:'extra', name:'hasStrongTiers', got:'抛异常: '+e.message, want:'true/false'}); }")
    return "\n".join(lines)


def js_str(s):
    if s is None:
        return "null"
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    core_path = os.path.join(root, "extension", "core.js")

    src = open(core_path, encoding="utf-8").read()
    # 去掉 ES module 的 export 前缀 → 变成普通脚本，可以直接内联执行
    stripped, n = re.subn(r"(?m)^export\s+", "", src)
    print("内核源码：%d 字节，去掉 %d 处 export 前缀" % (len(src), n))

    # 另外三个 JS 文件做语法检查（去掉 import/export 行后交给 new Function 解析）
    import json as _json
    syntax_items = []
    for fn in ("background.js", "content.js", "options.js"):
        p = os.path.join(root, "extension", fn)
        if not os.path.isfile(p):
            continue
        code = open(p, encoding="utf-8").read()
        code = re.sub(r"(?m)^\s*(import|export)\s+.*$", "", code)
        syntax_items.append({"name": fn, "code": code})
    syntax_js = _json.dumps(syntax_items, ensure_ascii=False)
    print("语法检查：%s" % "、".join(i["name"] for i in syntax_items))

    template = build_html(stripped, make_cases_js(), syntax_js)
    out_dir = os.path.join(root, "dist")
    os.makedirs(out_dir, exist_ok=True)
    html = os.path.join(out_dir, "_test_core.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write(template)

    edge = find_edge()
    if not edge:
        sys.exit("找不到 Edge，无法跑测试。")
    print("浏览器：%s" % edge)

    profile = tempfile.mkdtemp(prefix="yz_test_")
    url = "file:///" + html.replace("\\", "/")
    try:
        proc = subprocess.run(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run",
             "--user-data-dir=" + profile, "--dump-dom", url],
            capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        sys.exit("Edge 超时（90 秒），没拿到结果。")

    dom = proc.stdout.decode("utf-8", "replace")
    m = re.search(r"###RESULT###(.*?)###END###", dom, re.S)
    if not m:
        print("—— Edge 的原始输出（前 800 字）——")
        print(dom[:800])
        sys.exit("没在页面里找到测试结果（JS 可能一开始就报错了）。")

    import json
    rows = json.loads(m.group(1))

    groups = [("syntax", "JS 语法检查"), ("tier", "来源分级 tierOf"),
              ("verify", "引用校验硬闸门"),
              ("verdict", "总判定优先级 overallVerdict"), ("extra", "其他")]
    passed = failed = 0
    for key, title in groups:
        subset = [r for r in rows if r["g"] == key]
        if not subset:
            continue
        print("\n【%s】" % title)
        for r in subset:
            want = r.get("want")
            if key == "verify":
                # 特殊：验证剔除行为
                try:
                    v = json.loads(r["got"])
                    ok = (v["kept"] == ["真来源", "带空格的真来源"]
                          and sorted(v["dropped"]) == sorted(["模型编的", "空网址"]))
                    print("  %s %s" % ("✓" if ok else "✗", r["name"]))
                    print("      保留：%s" % v["kept"])
                    print("      剔除：%s" % v["dropped"])
                    for d in v["dropped"]:
                        if "编" in d:
                            print("      ↑ 模型编造的网址被拦住了 ✅")
                    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)
                except Exception:
                    print("  ✗ %s → %s" % (r["name"], r["got"]))
                    failed += 1
            elif want is None:
                print("  · %s → %s（未预设答案，供人工核对）" % (r["name"], r["got"]))
            else:
                ok = (r["got"] == want)
                print("  %s %-45s 实际=%-14s 期望=%s" % (
                    "✓" if ok else "✗", r["name"], r["got"], want))
                passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (passed, failed))
    print("=" * 60)
    if failed:
        print("\n⚠️ 有失败项 —— 先别提交商店，把上面的差异发我。")
        sys.exit(1)
    print("\n✅ 内核纯逻辑全部通过。")

    # 顺手把临时 profile 清掉
    try:
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
