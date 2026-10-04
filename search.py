# -*- coding: utf-8 -*-
"""搜索适配器层。

这是整个项目最重要的设计：**不绑定任何一家搜索服务**。
想加一家新的搜索，只要在这里写一个函数、注册进 PROVIDERS 即可，
其余代码一行都不用改。

统一返回格式：
    [{"title": 标题, "url": 网址, "content": 正文片段}, ...]
"""
import json
import pathlib
import threading
import time
import urllib.error
import urllib.request


class SearchError(Exception):
    pass


def _post_json(url, body, headers, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------- Tavily
def _tavily(cfg, query, limit, news_days=None):
    """Tavily：专为 AI 设计的搜索 API，直接返回干净正文。
    申请：https://app.tavily.com  免费额度：每月 1000 次（basic 搜索 1 次 = 1 credit）

    news_days 不为空时走**新闻模式**（topic=news + days=N）：
    只返回最近 N 天的新闻，结果带发布时间。实测有效。
    """
    key = cfg.get("TAVILY_API_KEY")
    if not key:
        raise SearchError(
            "没配置 TAVILY_API_KEY —— 去 https://app.tavily.com 申请，每月 1000 次免费"
        )
    body = {
        "api_key": key,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
    }
    if news_days:
        body["topic"] = "news"
        body["days"] = int(news_days)

    data = _post_json("https://api.tavily.com/search", body,
                      {"Content-Type": "application/json"})
    out = []
    for item in data.get("results", []):
        item_out = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": (item.get("content") or "")[:1200],
        }
        pub = item.get("published_date") or item.get("published")
        if pub:
            item_out["published"] = pub
        out.append(item_out)
    return out


# ---------------------------------------------------------------- 博查
def _bocha(cfg, query, limit, news_days=None):
    """博查（中文搜索，国内直连更快）。

    ⚠️ 注意：这个适配器**尚未实测验证**（我们还没有博查的 key）。
    接口地址和返回结构按公开文档写的，同时做了多种返回格式的兼容。
    等你拿到 key 后跑一次，如果报错把错误发我，我按真实返回改。
    """
    key = cfg.get("BOCHA_API_KEY")
    if not key:
        raise SearchError("没配置 BOCHA_API_KEY —— 去博查开放平台申请")
    body = {"query": query, "count": limit, "summary": True}
    if news_days:
        body["freshness"] = "oneWeek" if news_days <= 7 else "oneMonth"
    data = _post_json(
        cfg.get("BOCHA_ENDPOINT", "https://api.bochaai.com/v1/web-search"),
        body,
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )
    # 兼容几种可能的返回结构
    pages = (
        ((data.get("data") or {}).get("webPages") or {}).get("value")
        or ((data.get("webPages") or {}).get("value"))
        or ((data.get("data") or {}).get("value"))
        or []
    )
    out = []
    for item in pages[:limit]:
        out.append({
            "title": item.get("name") or item.get("title") or "",
            "url": item.get("url") or "",
            "content": (item.get("summary") or item.get("snippet")
                        or item.get("content") or "")[:1500],
        })
    return out


# ---------------------------------------------------------------- 模拟
def _mock(cfg, query, limit, news_days=None):
    """假搜索：不联网、不花额度，用来跑通流程 / 调试界面。"""
    tag = "（新闻模式）" if news_days else ""
    return [
        {
            "title": "[模拟结果]%s 关于「%s」的示例网页" % (tag, query),
            "url": "https://example.com/mock-1",
            "content": "这是模拟出来的检索片段，用来验证程序流程能跑通。"
                       "它不是真实网页，所以结论不可信，只用于调试。",
        },
        {
            "title": "[模拟结果]%s 另一篇相关文章" % tag,
            "url": "https://example.com/mock-2",
            "content": "同样是一条模拟结果。要得到真实结论，"
                       "请在 .env 里把 SEARCH_PROVIDER 改成 tavily 或 bocha。",
        },
    ][:limit]


PROVIDERS = {
    "tavily": _tavily,
    "bocha": _bocha,
    "mock": _mock,
}


# ---------------------------------------------------------------- 检索缓存
# 为什么必须要缓存？
# 实测发现：同一段文字连续跑 3 次，判定会在「可信 / 混合 / 证据不足」之间跳。
# 把模型温度降到 0 也没用 —— 因为变的是**检索结果**（每次搜回来的网页不一样），
# 证据变了结论自然变。一个核查工具"跑两次给两个答案"是致命的，
# 所以这里把检索结果落盘缓存：同样的 query 直接复用，保证可复现，顺带省钱。
CACHE_FILE = pathlib.Path(__file__).resolve().parent / "cache_search.json"
_CACHE = None
# 并发检索（check.gather_evidence 用线程池）会同时读写这个缓存。
# 不加锁的话，两次 write_text 可能交错，整个 cache_search.json 会变成坏 JSON，
# 之后所有查询都会静默退化成"每次都重新搜"。用 RLock 是因为写入路径要嵌套调用。
_CACHE_LOCK = threading.RLock()


def _load_cache():
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            try:
                _CACHE = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                _CACHE = {}
        return _CACHE


def _save_cache():
    with _CACHE_LOCK:
        try:
            CACHE_FILE.write_text(json.dumps(_CACHE, ensure_ascii=False),
                                  encoding="utf-8")
        except Exception:
            pass


def _cache_put(key, value):
    """线程安全地写入一条缓存并落盘。"""
    with _CACHE_LOCK:
        _load_cache()[key] = value
        _save_cache()


def cache_stats():
    c = _load_cache()
    return len(c)


def clear_cache():
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = {}
        try:
            CACHE_FILE.unlink()
        except Exception:
            pass


def web_search(cfg, query, limit=5, use_cache=True, news_days=None):
    name = (cfg.get("SEARCH_PROVIDER") or "tavily").lower()
    fn = PROVIDERS.get(name)
    if fn is None:
        raise SearchError(
            "未知的 SEARCH_PROVIDER：%s（可选：%s）" % (name, " / ".join(PROVIDERS))
        )

    try:
        days = float(cfg.get("CACHE_DAYS", "7") or 0)
    except Exception:
        days = 7.0
    key = "%s|%s|%d|%s" % (name, query, limit, news_days or "")

    if use_cache and days > 0:
        hit = _load_cache().get(key)
        if hit and time.time() - hit.get("t", 0) < days * 86400:
            return hit.get("r", [])

    results = fn(cfg, query, limit, news_days)

    if use_cache and days > 0 and results:
        _cache_put(key, {"t": time.time(), "r": results})
    return results
