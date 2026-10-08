# -*- coding: utf-8 -*-
"""读取配置：优先环境变量，其次同目录的 .env 文件。

为什么要 .env 而不是把 key 写进代码？
—— 因为代码要开源到 GitHub，key 一旦进代码就会被爬虫扫走。
"""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

# 允许通过环境变量覆盖的键
KEYS = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "SEARCH_PROVIDER",
    "TAVILY_API_KEY",
    "BOCHA_API_KEY",
    "BOCHA_ENDPOINT",
    "MAX_CLAIMS",
    "MAX_RESULTS",
    "MAX_EVIDENCE",
    "NEWS_DAYS",
    "CACHE_DAYS",
    "JUDGE_VOTES",
    "FULLTEXT",
    "FULLTEXT_PROVIDER",
    "FULLTEXT_MAX",
    "FULLTEXT_CHARS",
    "FULLTEXT_TIERS",
    "FULLTEXT_TIMEOUT",
    "EXCLUDE_DOMAINS",
    "FACT_CHECK_DOMAINS",
]

DEFAULTS = {
    "DEEPSEEK_MODEL": "deepseek-flash",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "SEARCH_PROVIDER": "tavily",   # tavily | bocha | mock
    "BOCHA_ENDPOINT": "https://api.bochaai.com/v1/web-search",  # 待验证
    "MAX_CLAIMS": "3",             # 一次最多核查几条断言（影响成本）
    "MAX_RESULTS": "4",            # 每种语言的搜索取几条
    "MAX_EVIDENCE": "6",           # 每条断言最终保留几条证据（按来源等级取舍）
    "NEWS_DAYS": "30",             # 近期事件追加新闻搜索的时间范围（天）；0 = 关闭
    "CACHE_DAYS": "7",             # 检索结果缓存天数（保证可复现 + 省钱）；设 0 关闭
    "JUDGE_VOTES": "1",            # 判定跑几次取多数。实测证据固定时判定是稳定的，
                                   # 所以默认 1 次；要紧的核查可以设 3（成本约 ×2.5）

    # ---- 全文抓取 ----
    # 搜索只给摘要片段，关键限定词常常不在摘要里。这里对够格下结论的来源（默认 A/B 级）
    # 再抓一次网页正文，让模型看到原文。
    "FULLTEXT": "1",               # 1 = 抓全文；0 = 只留搜索摘要（省钱/省时间）
    "FULLTEXT_PROVIDER": "auto",   # auto | tavily | http | off
                                   #   auto   = 有 Tavily key 走 /extract，否则免费 http
                                   #   tavily = Tavily /extract（质量最好，约 1 credit / 5 页）
                                   #   http   = 直接拉网页剥标签（免费，JS 渲染页抓不到）
    "FULLTEXT_MAX": "3",           # 每条断言最多抓几页全文（控制 token 成本）
    "FULLTEXT_CHARS": "3000",      # 每页正文截断到多少字
    "FULLTEXT_TIERS": "A,B",       # 只对这些等级抓全文。C/D 级本来就是线索，不值当
    "FULLTEXT_TIMEOUT": "20",      # 单个网页抓取超时（秒）

    # ---- 检索范围（站点定向 / 排除）----
    # 为什么只给「辟谣路」做定向？实测（2026-10-08）：
    #   Tavily 的 include_domains 是**硬过滤**，不是加权 ——
    #   域名池里没有该站的结果就直接返回 0 条（连 gov.cn 配辟谣查询都是 0 条）。
    #   所以它只适合用在"命脉清楚"的那一路：辟谣路本来就只想要辟谣平台的结果，
    #   而且这一路空了还有中文/英文/新闻三路兜底，不会把整条核查拖垮。
    #   反过来，对中文/英文路做定向 = 拿召回换精准，风险大得多。
    "FACT_CHECK_DOMAINS": "piyao.org.cn,kepuchina.cn,fact.qq.com",
                                   # 只作用于「辟谣 / fact check」那一路；留空 = 关闭
                                   # kepuchina.cn 会自动覆盖 piyao.kepuchina.cn 等子域

    # 排除内容农场 / 门户转载。实测（2026-10-08）：有效的机制是**腾出结果位** ——
    #   max_results 是固定的 4~5 个位子，垃圾占一个就少一个权威来源。
    #   低钠盐那条查询：排除前 A/B 级 1/5，排除后 2/5（挤进了辟谣平台和人民网）。
    # 注意：sources.py 已经把 D 级压住了（模型不许拿 D 级下结论），
    #   所以这里省的是 token 和干扰，不是"防模型用错来源"。
    "EXCLUDE_DOMAINS": ("baijiahao.baidu.com,csdn.net,jianshu.com,sohu.com,"
                        "163.com,toutiao.com,ifeng.com"),
                                   # 逗号分隔；留空 = 不排除。可以自己往里加
}


def parse_env_file(path):
    data = {}
    if not path.exists():
        return data
    # 用 utf-8-sig：Windows 记事本/PowerShell 保存的 UTF-8 会带 BOM，
    # 带 BOM 时第一个键名会变成 "\ufeffDEEPSEEK_API_KEY" 而读不到。
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def load():
    """返回一个普通的 dict，缺的键用默认值补上。"""
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in parse_env_file(ENV_FILE).items() if v})
    for k in KEYS:                       # 环境变量优先级最高
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    return cfg


def check_keys(cfg):
    """返回缺失配置的中文提示列表。"""
    problems = []
    if not cfg.get("DEEPSEEK_API_KEY"):
        problems.append("缺 DEEPSEEK_API_KEY —— 去 https://platform.deepseek.com/ 申请")
    provider = (cfg.get("SEARCH_PROVIDER") or "").lower()
    if provider == "tavily" and not cfg.get("TAVILY_API_KEY"):
        problems.append("缺 TAVILY_API_KEY —— 去 https://app.tavily.com 申请（每月 1000 次免费）")
    if provider == "bocha" and not cfg.get("BOCHA_API_KEY"):
        problems.append("缺 BOCHA_API_KEY —— 去博查开放平台申请")
    if provider not in ("tavily", "bocha", "mock"):
        problems.append("SEARCH_PROVIDER 只能是 tavily / bocha / mock，当前是 %r" % provider)

    fp = (cfg.get("FULLTEXT_PROVIDER") or "auto").lower()
    if fp not in ("auto", "tavily", "http", "off"):
        problems.append("FULLTEXT_PROVIDER 只能是 auto / tavily / http / off，当前是 %r" % fp)
    if fp == "tavily" and not cfg.get("TAVILY_API_KEY"):
        problems.append("FULLTEXT_PROVIDER=tavily 但缺 TAVILY_API_KEY —— 改成 auto 或 http 也行")
    return problems
