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
    return problems
