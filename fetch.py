# -*- coding: utf-8 -*-
"""全文抓取：把「搜索摘要」升级成「网页正文」。

为什么要这一步？
    搜索引擎（Tavily / 博查）只给我们一段摘要片段。模型拿摘要下结论，
    最怕的是"断言里那个关键限定词恰好不在摘要里" —— 摘要说"低钠盐有助于
    控血压"，正文里还有一句"但肾功能不全者禁用"。只看摘要，模型会判
    「可信」；看了正文，才知道原话被绝对化了。

    所以：先把候选证据按来源等级筛一遍，只对**够格下结论的那几条**（默认 A/B 级）
    去抓正文，其余照旧看摘要。这样成本可控。

为什么不在搜索时直接开 include_raw_content？
    Tavily 确实支持，但那是**每一个搜索请求、每一条结果**都返回整页正文 ——
    一次核查有 6~9 路检索、每路 4 条，等于一次拉回 30 多页全文，绝大部分根本
    用不上（_pick 之后每条断言只留 3~6 条）。而且搜索结果的缓存条数会暴涨。
    正确的位置是**证据筛完之后的补刀**，所以单独放在这个文件里。

两条抓取路径：
    tavily —— Tavily /extract 接口，质量最好（能处理 JS 渲染页、PDF），
              1 credit / 5 个网址，按量计费。
    http   —— 直接 urllib 拉 HTML 再剥标签，**完全免费**，但对 JS 渲染的站点无效。
    auto   —— 有 Tavily key 就用 tavily，否则退回 http。
"""
import html
import json
import pathlib
import re
import threading
import time
import urllib.error
import urllib.request

import sources


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- 缓存
# 同一个网址在一次核查里可能被多条断言命中，跨次核查也会重复出现。
# 不缓存的话，同一页会被反复抓 —— 既慢又费额度。
FETCH_CACHE_FILE = pathlib.Path(__file__).resolve().parent / "cache_fetch.json"
_CACHE = None
_LOCK = threading.RLock()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _load_cache():
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            try:
                _CACHE = json.loads(FETCH_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                _CACHE = {}
        return _CACHE


def _save_cache():
    with _LOCK:
        try:
            FETCH_CACHE_FILE.write_text(
                json.dumps(_CACHE, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def clear_cache():
    global _CACHE
    with _LOCK:
        _CACHE = {}
        try:
            FETCH_CACHE_FILE.unlink()
        except Exception:
            pass


def cache_stats():
    return len(_load_cache())


# ---------------------------------------------------------------- HTML 处理
_KILL = re.compile(r"(?is)<(script|style|noscript|svg|head|nav|footer)\b[^>]*>.*?</\1\s*>")
_BREAK = re.compile(r"(?is)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)\s*>")
_TAG = re.compile(r"(?s)<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0\u3000]+")
_NEWLINES = re.compile(r"\s*\n\s*")

# 页面里没用的样板段：登录提示、版权、cookie 声明。留着只会白占 token。
_JUNK_LINES = (
    "版权所有", "京ICP备", "沪ICP备", "粤ICP备", "网站地图", "关注我们",
    "扫码关注", "上一篇", "下一篇", "责任编辑", "免责声明",
    "all rights reserved", "cookie", "subscribe to our newsletter",
    "sign up for", "privacy policy",
)


_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _clean_md(raw):
    """Tavily 返回的是 markdown，带图片语法和链接 URL 噪声。

    图片直接删掉（我们本来也读不了图），链接只留文字不留下网址 ——
    网址会白占 token，而且模型已经能从证据里看到 url 字段了。
    """
    t = _MD_IMG.sub(" ", raw)
    t = _MD_LINK.sub(r"\1", t)
    t = _SPACES.sub(" ", t)
    out = []
    for ln in t.split("\n"):
        ln = ln.strip().strip("*#->").strip()
        if ln:
            out.append(ln)
    return "\n".join(out)


def _strip_html(raw):
    """把 HTML 变成可读正文。不追求完美，够模型读懂就行。"""
    t = _KILL.sub(" ", raw)
    t = _BREAK.sub("\n", t)
    t = _TAG.sub(" ", t)
    t = html.unescape(t)
    t = _SPACES.sub(" ", t)

    lines = []
    for ln in t.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        low = ln.lower()
        if any(j.lower() in low for j in _JUNK_LINES):
            continue
        # 极短的行基本是导航/按钮文字，丢
        if len(ln) < 6 and not re.search(r"[\u4e00-\u9fff]", ln):
            continue
        lines.append(ln)
    return "\n".join(lines)


def _decode(raw_bytes, content_type):
    """猜编码。中文站点大量用 GBK/GB18030，只按 utf-8 解会全是乱码。"""
    cands = []
    m = re.search(r"charset=[\"']?([\w-]+)", content_type or "", re.I)
    if m:
        cands.append(m.group(1))
    m2 = re.search(rb"charset=[\"']?([\w-]+)", raw_bytes[:4000], re.I)
    if m2:
        cands.append(m2.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "gb18030"]
    for enc in cands:
        try:
            return raw_bytes.decode(enc)
        except Exception:
            continue
    return raw_bytes.decode("utf-8", "replace")


# ---------------------------------------------------------------- http 抓取
def _http_one(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(3_000_000)          # 3MB 上限，防大文件拖死
    if "pdf" in ctype.lower():
        raise FetchError("PDF 需走 tavily 通道（http 通道不支持）")
    if "html" not in ctype.lower() and "xml" not in ctype.lower() and "text" not in ctype.lower():
        raise FetchError("非网页内容：%s" % ctype)
    return _strip_html(_decode(raw, ctype))


def _http_many(cfg, urls):
    out = {}
    timeout = float(cfg.get("FULLTEXT_TIMEOUT", "20") or 20)
    for u in urls:
        try:
            txt = _http_one(u, timeout)
        except Exception as e:
            _note("%s 免费通道失败：%s" % (u, e))
            continue
        if txt:
            out[u] = txt
    return out


# 最近一次失败的说明，给 --debug 用。
# 抓正文失败的原因（SSL、403、超时）必须能看见 —— 否则"全文已开却 0 篇"
# 会被误读成"这些网站没正文"。
_LAST_ERROR = []


def _note(msg):
    if len(_LAST_ERROR) < 10:
        _LAST_ERROR.append(msg)


def last_errors():
    return list(_LAST_ERROR)


# ---------------------------------------------------------------- tavily 抓取
def _post_json(url, body, headers, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ukey(u):
    """网址归一化：用来把返回结果对回请求网址（可能被重定向）。"""
    s = (u or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s, flags=re.I)
    return re.sub(r"^www\.", "", s, flags=re.I)


def _tavily_many(cfg, urls):
    """Tavily /extract。一次最多 20 个网址，超了分批。"""
    key = cfg.get("TAVILY_API_KEY")
    if not key:
        raise FetchError("没配置 TAVILY_API_KEY")
    timeout = float(cfg.get("FULLTEXT_TIMEOUT", "20") or 20) * 3

    out = {}
    for i in range(0, len(urls), 20):
        batch = urls[i:i + 20]
        data = None
        # 直连 TLS 会偶发 SSL 断连（这台机器上实测过：同一批请求前后两次，
        # 一次成功一次 UNEXPECTED_EOF）。失败重试一次，不做更多 ——
        # 重试太多次只是把"抓不到"拖慢成 3 倍时间。
        for attempt in (1, 2):
            try:
                data = _post_json(
                    "https://api.tavily.com/extract",
                    {"api_key": key, "urls": batch, "extract_depth": "basic",
                     "format": "markdown"},
                    {"Content-Type": "application/json"},
                    timeout=timeout,
                )
                break
            except Exception as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                if attempt == 1:
                    time.sleep(1.5)
                    continue
                _note("Tavily /extract 失败：%s %s %s" % (type(e).__name__, e, detail))
        if not data:
            continue
        for fr in data.get("failed_results") or []:
            _note("Tavily 抓不到 %s：%s" % (fr.get("url"), fr.get("error")))
        for r in data.get("results", []):
            u = r.get("url") or ""
            body = _clean_md(r.get("raw_content") or "")
            if not body:
                continue
            # 先按归一化网址对回请求列表，对不上就原样留着
            for req_u in batch:
                if _ukey(req_u) == _ukey(u):
                    out[req_u] = body
                    break
            else:
                out[u] = body
    return out


# ---------------------------------------------------------------- 对外接口
def _provider(cfg):
    p = (cfg.get("FULLTEXT_PROVIDER") or "auto").lower()
    if p == "auto":
        return "tavily" if cfg.get("TAVILY_API_KEY") else "http"
    return p


def extract(cfg, urls, use_cache=True):
    """抓一组网址的正文，返回 {网址: 正文}。

    失败的网址直接不出现在结果里 —— 调用方按需回退到摘要即可，
    不要因为一页抓不到就让整条核查失败。
    """
    prov = _provider(cfg)
    if prov == "off" or not urls:
        return {}

    try:
        days = float(cfg.get("CACHE_DAYS", "7") or 0)
    except Exception:
        days = 7.0

    out, todo = {}, []
    now = time.time()
    cache = _load_cache()
    for u in urls:
        hit = cache.get(u)
        # 只认"抓到了正文"的缓存。空记录一律当未命中重试 ——
        # 否则一次网络抖动（SSL 断连、超时）会把"抓不到"写进缓存锁住好几天，
        # 之后所有核查都静默退化成只看摘要，而且没人知道为什么。
        if use_cache and days > 0 and hit and hit.get("text") \
                and now - hit.get("t", 0) < days * 86400:
            out[u] = hit["text"]
            continue
        todo.append(u)

    if todo:
        got = {}
        if prov == "tavily":
            try:
                got = _tavily_many(cfg, todo)
            except FetchError as e:
                _note("Tavily 通道不可用：%s" % e)
                got = {}
        # tavily 没抓到的，用免费通道再兜一次（对国内静态站往往反而更灵）
        missing = [u for u in todo if u not in got]
        if missing and prov in ("tavily", "http"):
            got.update(_http_many(cfg, missing))
        out.update(got)

        if use_cache and days > 0 and got:
            with _LOCK:
                c = _load_cache()
                for u, txt in got.items():
                    if txt:
                        c[u] = {"t": now, "text": txt}
                _save_cache()

    return out


def enrich(cfg, claims, on_progress=None):
    """给 claims 里每条证据补正文。就地修改，返回补成功的条数。

    只对 FULLTEXT_TIERS 指定的等级抓（默认 A、B）—— C/D 级来源本来就不够格
    支撑判定，给它们抓全文纯属烧 token。
    """
    if str(cfg.get("FULLTEXT", "1")).lower() in ("0", "off", "false", "no", ""):
        return 0
    if _provider(cfg) == "off":
        return 0

    allowed = set()
    for lv in (cfg.get("FULLTEXT_TIERS", "A,B") or "").split(","):
        lv = lv.strip().upper()
        if lv:
            allowed.add(lv)
    if not allowed:
        return 0

    try:
        cap = int(cfg.get("FULLTEXT_MAX", "3") or 3)
    except Exception:
        cap = 3
    try:
        chars = int(cfg.get("FULLTEXT_CHARS", "3000") or 3000)
    except Exception:
        chars = 3000

    targets = []                          # [(证据对象, 网址)]
    for c in claims:
        n = 0
        for e in c.get("evidence") or []:
            tier = (e.get("tier") or "")
            if tier[:1].upper() not in allowed:
                continue
            if n >= cap:
                break
            e["fulltext"] = False
            if e.get("url"):
                targets.append((e, e["url"]))
                n += 1

    if not targets:
        return 0

    urls = list(dict.fromkeys(u for _e, u in targets))
    if on_progress:
        on_progress(len(urls))
    _LAST_ERROR.clear()
    texts = extract(cfg, urls)

    hit = 0
    for e, u in targets:
        txt = texts.get(u)
        if not txt:
            continue
        e["summary"] = e.get("content", "")      # 原摘要留着，方便排查
        e["content"] = txt[:chars]
        e["fulltext"] = True
        e["fulltext_len"] = len(txt)
        hit += 1

    # 一篇都没抓到，把原因挂到断言上 —— 让界面/日志能说清是"网站拒绝"
    # 还是"SSL 断了"，而不是干巴巴一个"0 篇"。
    if hit == 0:
        errs = "；".join(_LAST_ERROR) or "未知原因"
        for c in claims:
            if c.get("evidence"):
                c["fulltext_error"] = errs
    return hit
