# -*- coding: utf-8 -*-
"""核查主流程：拆断言 → 检索证据 → 来源分级 → 基于证据判定 → 校验引用。

三个阶段：两次模型调用 + 一次搜索调用。
    1. extract_claims  把一段话拆成可核查的断言（≤ MAX_CLAIMS 条）
    2. gather_evidence 每条断言去搜网页，并给每条结果打上来源等级
    3. judge           把「断言 + 分级后的证据」交给模型判定
    4. verify_sources  硬闸门：模型引用的网址必须真的在检索结果里，否则剔除
"""
import concurrent.futures
import copy
import hashlib
import json
import pathlib
import re
import time

import llm
import fetch
import search
import sources

# ---------------------------------------------------------------- 结果缓存
# 为什么要有这层？
# 实测：同一段文字连跑 3 次，判定在「可信 / 混合 / 证据不足」之间跳。
# 根因链条是：拆断言的措辞每次略有不同 → 搜索关键词变 → 缓存未命中
# → 搜到不同证据 → 结论翻转。把温度降到 0 也没用。
#
# 对一个核查工具来说，"同一段文字跑两次给两个答案"是致命的。
# 所以这里把**整条核查结果**按输入文字的哈希缓存起来：
# 同一段文字永远得到同一个答案，第二次核查还完全免费。
#
# ⚠️ 改提示词或改流程之后，必须把 PROMPT_VERSION +1，否则会命中旧结论。
#    注意「流程」不只有提示词 —— 检索策略（几路查询、关键词怎么拼）也算。
#    v8：多了一路「辟谣 / fact check」检索，检索改为并发发出。
#    v9：判定提示词加第 11 条 —— A/B 级来源明确冲突且无更高层级裁决时，必须判 insufficient。
#    v10：证据不再只有搜索摘要 —— 对 A/B 级来源抓网页正文（fetch.py），
#         判定时看到的是原文，且块里标了「全文 / 摘要」。
#    v11：加第 12 条提示词护栏（"证据更长 ≠ 可以下更强结论"）—— 评测显示
#         v10 上线后有样本因为读到更多支持性正文而变得过度自信、反而判错。
#         检索侧同时加了「辟谣路站点定向」和「排除内容农场」。
PROMPT_VERSION = "11"
RESULT_CACHE_FILE = pathlib.Path(__file__).resolve().parent / "cache_result.json"
_RESULT_CACHE = None


def _load_result_cache():
    global _RESULT_CACHE
    if _RESULT_CACHE is None:
        try:
            _RESULT_CACHE = json.loads(RESULT_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _RESULT_CACHE = {}
    return _RESULT_CACHE


def _save_result_cache():
    try:
        RESULT_CACHE_FILE.write_text(
            json.dumps(_RESULT_CACHE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _normalize_text(text):
    """归一化：去掉空白和常见标点，全半角统一，避免"同样的话打空格不同"就绕过缓存。"""
    t = (text or "").strip().lower()
    drop = set(" \t\r\n，,。.、·:：;；!！?？\"'“”‘’()（）[]【】-—_/\\")
    return "".join(ch for ch in t if ch not in drop)


def _result_key(cfg, text):
    raw = "|".join([
        PROMPT_VERSION,
        _normalize_text(text),
        str(cfg.get("SEARCH_PROVIDER")),
        str(cfg.get("MAX_CLAIMS")),
        str(cfg.get("MAX_RESULTS")),
        str(cfg.get("JUDGE_VOTES")),
        str(cfg.get("DEEPSEEK_MODEL")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def clear_result_cache():
    global _RESULT_CACHE
    _RESULT_CACHE = {}
    try:
        RESULT_CACHE_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------- 拆断言缓存
# 为什么必须有这一层？
#
# 评测的可复现性坏在**第一步**：同一段文字两次拆出的措辞略有不同
#   → 搜索关键词变 → 检索缓存未命中 → 搜到不同证据 → 结论翻转
# 实测证据（2026-10-04）：两次评测之间**没有任何针对某条样本的改动**，
# 它自己从"判错"变成了"判对" —— 噪声下限至少 ±1 条。
# 于是所有"改动到底有没有效"的判断都失去了意义。
#
# 把拆断言的结果按文本固定下来，A/B 对比一次改动才谈得上干净。
#
# ⚠️ SPLIT_VERSION 只在【第一步的提示词或参数】变化时 +1。
#    千万不要跟着 PROMPT_VERSION 一起动 —— 否则改判定提示词会把已经固定的
#    拆断言一并冲掉，噪声又回来了，而你会以为是自己改的规则起了作用。
SPLIT_VERSION = "1"
CLAIM_CACHE_FILE = pathlib.Path(__file__).resolve().parent / "cache_claims.json"
_CLAIM_CACHE = None


def _load_claim_cache():
    global _CLAIM_CACHE
    if _CLAIM_CACHE is None:
        try:
            _CLAIM_CACHE = json.loads(CLAIM_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _CLAIM_CACHE = {}
    return _CLAIM_CACHE


def _save_claim_cache():
    try:
        CLAIM_CACHE_FILE.write_text(
            json.dumps(_CLAIM_CACHE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _claim_key(cfg, text):
    raw = "|".join([
        SPLIT_VERSION,
        _normalize_text(text),
        str(cfg.get("MAX_CLAIMS")),
        str(cfg.get("DEEPSEEK_MODEL")),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def clear_claim_cache():
    global _CLAIM_CACHE
    _CLAIM_CACHE = {}
    try:
        CLAIM_CACHE_FILE.unlink()
    except Exception:
        pass

VERDICT_LABEL = {
    "supported": "可信",
    "refuted": "与事实不符",
    "insufficient": "证据不足",
    "mixed": "部分属实",
}
VALID_VERDICTS = tuple(VERDICT_LABEL)

STEP1_SYSTEM = """你是事实核查助手的第一步：拆分断言。

把用户给的文字拆成可以独立核查的「事实性断言」。规则：
1. 最多拆成 {max_claims} 条，优先挑最关键、最具体的。
2. 只保留客观可查的陈述（时间、地点、数字、事件、机构、政策）。
3. 观点、情绪、预测、"我觉得"这类主观表述一律丢掉。
4. 如果整段话都没有可核查的断言，claims 返回空列表 []。
5. query：中文搜索关键词，要精炼，不要照抄整句。
6. query_en：**同一件事的英文搜索关键词，必须给**。我们要拿它去英文资料里找证据
   （科普、健康、科学类内容，英文资料的质量和数量都明显更好）。
   原话本来就是英文时，query_en 填同样的词即可。
7. time_sensitive：这条断言涉及**近期事件**（今年、最近、昨天、刚发生、
   某个具体日期之后的事）就填 true；属于长期成立的常识/科学结论就填 false。

只输出 JSON，不要任何解释：
{{"claims":[{{"claim":"断言原文","query":"中文关键词","query_en":"english keywords","time_sensitive":false}}]}}"""

STEP3_SYSTEM = """你是事实核查的第二步：基于证据下结论。

你**只能**依据下面给出的【证据】来判断，禁止使用你自己的记忆、常识或推测来补充事实。

每条证据都标好了来源等级，含义如下，**不要自己重新判断等级**：
- A 官方一手：政府、公立机构、原始文件、正式公告
- A 当事方官网：**当事机构/企业自己的网站**（如 openai.com、microsoft.com）。
  它只能用来证明「关于该机构自身的客观事实」——成立时间、发布了什么产品、
  官方公告说了什么。**不能用它证明"效果更好/更安全/行业第一"这类主张**，那是自我宣传。
- B 权威媒体：央媒、官方通讯社、正规媒体、知名科普媒体
- C 专业机构：科普机构、医院、高校、学术数据库、标准组织
- D 自媒体百科：微博、公众号、知乎、百科、门户转载、论坛
- 未分级：无法判断来路

方括号里还有一个词说明**这条证据我们看到了多少**：
- `全文` = 已抓取整页正文。里面没写的限定条件，基本可以认为原文确实没有。
- `仅摘要` = 只是搜索返回的片段，**原文未在片段中出现的信息不代表没有**。
  据此下 supported / refuted 之前要留一分余地；拿不准就判 insufficient。

对每条断言给出一个判定：
- supported    证据明确支持该断言
- refuted      证据明确与断言矛盾
- insufficient 证据不足、证据互相冲突、或只有弱来源
- mixed        断言**部分成立**：主要事实有依据，但措辞被绝对化，而证据里存在成文的例外

**判定门槛（重要）**：
1. 要给出 supported 或 refuted，**必须至少有一条 A / A当事方 / B 级证据直接支持这个结论**。
2. C 级来源（专业机构、科普、医院、学术）：可以支撑判定，但 confidence 不超过 0.6。
3. D 级来源（自媒体、百科、论坛、平台转载）**只能当线索，不能作为判定依据**；
   只有 D 级时必须判 insufficient。
4. **「未分级」不等于低质量**，它只表示我们认不出这个网站的来路：
   - 只有 1 条未分级来源 → 判 insufficient；
   - 有 **2 条及以上相互独立**的未分级来源、结论一致 → 可以据此判定，
     但 confidence 不超过 0.6，并在 reason 里注明"来源未分级"。
5. **当事方官网要克制使用**：企业官网说"我们的产品更安全/效果更好"**不算证据**。
   它只能支撑「该机构自己做过什么、说过什么、什么时候成立/发布」这类客观事实。
   遇到"优劣、效果、安全性"类主张，必须另找第三方来源。
6. 官方公告与自媒体转述冲突时，以官方为准。
7. 证据不足时必须选 insufficient，不许猜。

**最容易搞错的几条规则，务必遵守**：

8. **mixed（部分属实）的门槛很高**，必须**同时**满足：
   ① A/B 级来源**正面支持**该断言的核心主张；
   ② 同一来源同时指出存在**成文的例外或范围限制**；
   ③ 原话措辞是绝对的（"都""一律""不再""千万别""肯定"）。

   以下情形**禁止**使用 mixed：
   - 核心主张已被 A/B 级来源明确否证 → 判 **refuted**（哪怕文中某一句恰好为真）
   - 例外面向的是**另一类特定人群**（肾病患者、孕妇、婴幼儿等），
     而原话是对一般人的普遍断言 → 判 **refuted**
   - 你只是拿不准 → 判 **insufficient**。
     **mixed 不是"折中档"，不许当保险选项用。**

9. **中央口径 vs 地方做法**：国家部委/中央机关的正式口径代表全国一般情况，
   个别地方保留的旧做法属于例外。判断"全国均已实现"这类表述时以中央口径为主，
   若原话绝对而地方确有成文例外，按第 8 条判 mixed，
   并在 reason 里同时写明中央口径和地方例外。**不要因为一句例外就把整体判成 refuted。**

10. **时效**：以最新、且层级最高的来源为准；旧文件被新文件取代时，以新文件为准。
   证据里如果带发布时间（近期新闻类结果会有），用它判断新旧。

11. **权威之间没有定论时，必须判 insufficient**（评测里最容易掉分的一条）：

    当 A/B 级来源之间对同一问题给出**明确相反的结论**，而证据里**没有更高层级的
    来源作出裁决**时，必须判 **insufficient**，并在 reason 里点出冲突的双方。

    典型情形（真实样例）：一个国际机构把某物列为"可能致癌"（2B 类），
    同时另一个同级权威机构维持"每日允许摄入量不变"。
    这是**权威机构之间尚未达成一致**，不是"你可以自己挑一边"。
    **不许挑一条更符合直觉的来判 supported 或 refuted**，哪怕你觉得某一方更权威。

    反过来同样重要 —— **别把这条当成万能挡箭牌**：
    只有证据里**确实存在相互冲突的 A/B 级来源**时才适用。
    如果 A/B 级来源**一致地否证**了该断言，仍然判 **refuted**。
    如果只是你自己拿不准、或者证据偏少，那是第 7 条管的事，不是这一条。

12. **证据更长 ≠ 可以下更强的结论**（实测踩过，务必遵守）：

    部分来源下面会标 `全文`，意思是这段是**整页正文**，不是搜索片段。
    读到的内容变多，**不构成**放宽第 8 条 mixed 门槛的理由，也**不构成**
    把 insufficient 改判成 supported / refuted 的理由。

    真实反例：一条断言在只看到搜索摘要时被判 `mixed`（措辞绝对 + 存在成文例外，
    是对的）；看到整页正文后，模型因为读到了更多**支持性**细节而改判成更确定的
    结论，反而离正确答案更远。在另一条同类样本上，同样的"变得更确定"把它从
    `mixed` 推到了 `supported`，而正确答案是 `insufficient`。

    所以判断"措辞是否被绝对化"，看的是**有没有成文的例外或范围限制**，
    不是"支持的证据看起来够不够多"。证据变多只是把同一道门槛喂得更饱，
    **门槛本身不移动**。

其他要求：
- sources 里的 url 只能从【证据】中原样复制，**禁止编造任何网址**。
- reason 用一句中文说清依据，不超过 60 字，并点出关键来源属于哪一级；
  证据互相冲突时，必须在 reason 里点出冲突双方。
- 有明确 A 级一手来源时，confidence 可以给到 0.85 以上；仅靠 B 级给 0.6~0.8；
  只靠 C 级或未分级不超过 0.6；证据互相矛盾时不要超过 0.6。

只输出 JSON，不要任何解释：
{{"results":[{{"claim":"断言原文","verdict":"supported|refuted|insufficient|mixed","confidence":0.0,"reason":"判定依据","sources":[{{"url":"网址","title":"标题"}}]}}]}}"""


def extract_claims(cfg, text, use_cache=True):
    """第一步：拆断言。返回 (claims列表, usage)。

    use_cache=True 时按文本缓存拆分结果，保证同一段文字每次拆出**完全一样**的
    断言和关键词（见上面「拆断言缓存」那段说明）。命中缓存时 usage 返回 {}。
    """
    try:
        days = float(cfg.get("CACHE_DAYS", "7") or 0)
    except Exception:
        days = 7.0

    key = _claim_key(cfg, text)
    if use_cache and days > 0:
        hit = _load_claim_cache().get(key)
        if hit and time.time() - hit.get("t", 0) < days * 86400:
            # 返回副本：下游 gather_evidence 会往 claim 上挂 evidence、queries、
            # fulltext_error。直接交出缓存里的对象，这些改写就写回缓存了。
            return copy.deepcopy(hit.get("claims", [])), {}

    prompt = STEP1_SYSTEM.format(max_claims=cfg.get("MAX_CLAIMS", "3"))
    try:
        data, usage = _chat_json(cfg, prompt, text, 2048)
    except JsonRetryError as e:
        raise ClaimParseError(str(e), e.usage)
    claims = data.get("claims") or []
    limit = int(cfg.get("MAX_CLAIMS", 3))
    clean = []
    for c in claims[:limit]:
        if not isinstance(c, dict):
            continue
        claim = (c.get("claim") or "").strip()
        if not claim:
            continue
        clean.append({
            "claim": claim,
            "query": (c.get("query") or claim).strip(),
            "query_en": (c.get("query_en") or "").strip(),
            "time_sensitive": bool(c.get("time_sensitive")),
        })

    if use_cache and days > 0 and clean:
        # ⚠️ 必须存**副本**。gather_evidence 会往 claim 上挂 evidence / queries /
        # fulltext_error，而它是就地改写的 —— 存引用的话，下一次任意一条样本
        # 触发 _save_claim_cache() 时，整个字典（连同这些被改写过的 claim）
        # 一起落盘，拆断言缓存会越滚越大。实测过：19 条样本跑完，
        # cache_claims.json 从 281 字节涨到 496KB，里面塞满了整页网页正文。
        _load_claim_cache()[key] = {"t": time.time(),
                                    "claims": copy.deepcopy(clean)}
        _save_claim_cache()
    return clean, usage


_TIER_RANK = {sources.A: 0, sources.PARTY: 1, sources.B: 2,
              sources.C: 3, sources.UNKNOWN: 4, sources.D: 5}


def _norm_query(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _pick(pool, cap):
    """去重 → 按来源等级排序 → 截断。

    证据条数有上限（为了控制 token 成本），所以让 A/B 级来源先占位置，
    弱来源被挤掉。这是"双语搜索"能把成本控制住的关键。
    """
    seen, picked = set(), []
    for r in sorted(pool, key=lambda x: _TIER_RANK.get(x.get("tier"), 3)):
        u = (r.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        picked.append(r)
        if len(picked) >= cap:
            break
    return picked


_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")


def _fact_check_query(c):
    """给每条断言多配一路「辟谣 / fact check」检索。

    为什么值得多搜这一路：事实核查类站点（中国互联网联合辟谣平台、腾讯较真、
    Snopes、FactCheck.org）在搜索结果里本来就排得靠前，但**必须用对关键词**才能
    把它们勾出来 —— 用断言原话去搜，往往搜到的还是原始谣言本身。
    多一次检索的成本，换"有没有人已经核查过这句话"的直接答案，很划算。
    """
    q = (c.get("query") or c.get("claim") or "").strip()
    if not q:
        return ""
    if _HAS_CJK.search(q):
        return q + " 辟谣 真相"
    return q + " fact check"


def gather_evidence(cfg, claims, on_progress=None, max_workers=4):
    """第二步：每条断言去搜网页。

    对每条断言最多搜四次：
      1. 中文关键词
      2. 英文关键词（科普/健康/科学类内容，英文资料质量明显更好）
      3. 辟谣 / fact check 关键词（直接去找有没有人已经核查过这句话）
         —— 这一路会用 FACT_CHECK_DOMAINS 做**站点定向**（见下面的说明）
      4. 若这条断言涉及近期事件且开了新闻模式 → 再加一次新闻搜索（带时间范围）

    这几路检索之间**没有任何依赖**，所以并发发出。串行跑纯属白等：
    一次核查 6~9 路检索，串行要十几秒，并发后只剩最慢那一路的时间。
    限并发 4 —— 搜索服务有限流，一次全发出去容易吃 429。

    结果合并去重后按来源等级排序、截断，挂在 claim["evidence"] 上。
    最后再对够格下结论的证据抓一次网页正文（见 fetch.py），把摘要换掉。
    """
    limit = int(cfg.get("MAX_RESULTS", 4))
    cap = int(cfg.get("MAX_EVIDENCE", 6))
    try:
        news_days = int(cfg.get("NEWS_DAYS", 0) or 0)
    except Exception:
        news_days = 0

    # ① 摊平所有检索任务
    # 辟谣路的站点定向：Tavily 的 include_domains 是**硬过滤**（实测：给不存在的
    # 域名返回 0 条，给 gov.cn 配辟谣查询也是 0 条）。所以只在辟谣路用 ——
    # 这一路本来就只想要辟谣平台的结果，而且它空了还有中文/英文/新闻三路兜底。
    # 对中文/英文路做定向是拿召回换精准，风险大得多，不划算。
    fc_domains = search.split_domains(cfg.get("FACT_CHECK_DOMAINS"))

    jobs = []
    for idx, c in enumerate(claims):
        q = c["query"] or c["claim"]
        queries = [(q, None, "中文", None)]
        qe = c.get("query_en") or ""
        if qe and _norm_query(qe) != _norm_query(q):
            queries.append((qe, None, "英文", None))
        fq = _fact_check_query(c)
        if fq and _norm_query(fq) not in (_norm_query(q), _norm_query(qe)):
            queries.append((fq, None, "辟谣", fc_domains or None))
        if c.get("time_sensitive") and news_days > 0:
            queries.append((q, news_days, "新闻", None))
        c["queries"] = ["%s:%s" % (m, qq) for qq, _, m, _d in queries]
        for query, days, mode, doms in queries:
            jobs.append((idx, query, days, mode, doms))

    # ② 并发检索。结果按任务序号收集，最后仍按原顺序拼装：
    #    _pick 的排序是稳定的，同等级来源之间靠输入顺序取舍 ——
    #    不按序号回收的话，证据顺序会随线程完成顺序变化，结论就不可复现了。
    got = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {}
        for n, (idx, query, days, mode, doms) in enumerate(jobs):
            if on_progress:
                on_progress(claims[idx], "[%s] %s" % (mode, query))
            futs[ex.submit(search.web_search, cfg, query, limit, True, days, doms)] = n
        for fut in concurrent.futures.as_completed(futs):
            n = futs[fut]
            idx = jobs[n][0]
            try:
                got[n] = [sources.annotate(r) for r in fut.result()]
            except search.SearchError:
                raise
            except Exception as e:
                claims[idx]["search_error"] = "%s: %s" % (type(e).__name__, e)

    # ③ 按任务顺序拼回证据池，再按来源等级取舍
    pools = [[] for _ in claims]
    for n, (idx, _q, _days, _mode, _doms) in enumerate(jobs):
        pools[idx].extend(got.get(n, []))
    for c, pool in zip(claims, pools):
        c["evidence"] = _pick(pool, cap)

    # ④ 补全文：搜索只给摘要，这里对够格下结论的来源（默认 A/B 级）抓一次网页正文。
    #    放在 _pick **之后**是关键 —— 只抓最终要用的那几页，而不是每路检索的每条结果。
    if on_progress:
        on_progress(None, "抓取网页正文…")
    try:
        n_full = fetch.enrich(cfg, claims)
    except Exception as e:
        # 抓正文失败不该拖垮整条核查：退回摘要照常判定
        n_full = 0
        for c in claims:
            c["fulltext_error"] = "%s: %s" % (type(e).__name__, e)
    if on_progress:
        on_progress(None, "正文已取 %d 篇" % n_full)
    return claims


class JudgeParseError(Exception):
    """判定模型吐出的 JSON 三级兜底都救不回来。"""

    def __init__(self, msg, usage=None):
        super().__init__(msg)
        self.usage = usage or {}


class ClaimParseError(Exception):
    """第一步（拆断言）的 JSON 三级兜底都救不回来。

    和 JudgeParseError 分开，是因为两者的降级方式不同：
    判定失败可以逐条降成"无法判定"，而拆断言失败意味着后面整条流水线没得跑。
    """

    def __init__(self, msg, usage=None):
        super().__init__(msg)
        self.usage = usage or {}


class JsonRetryError(Exception):
    """模型 JSON 输出经过"重试 + 修复"后仍解析不了。带着 usage，账照记。"""

    def __init__(self, msg, usage=None):
        super().__init__(msg)
        self.usage = usage or {}


def _repair_json(raw):
    """尽力从模型输出里救出 JSON：去掉 ``` 围栏、截取最外层 {}。"""
    s = (raw or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return s


def _chat_json(cfg, system, user, max_tokens):
    """调模型 + 解析 JSON，带三级兜底。返回 (data, usage)。

    ① 原样解析 ② 追加一句"必须输出合法 JSON"后重试 ③ 去 ``` 围栏 / 截最外层 {}

    **第一步和第三步都要用这一套。** 原来只有判定那一步有兜底，拆断言那一步
    直接 `llm.parse_json(raw)` —— 评测里 r04 就死在这里（模型第一条断言吐了
    被截断的 JSON），一条样本直接报错、白花前面所有的钱。同一类风险不该
    只在一半的代码里防。
    """
    raw, usage = llm.chat(cfg, system, user, max_tokens=max_tokens, temperature=0.0)
    try:
        return llm.parse_json(raw), usage
    except Exception as first:
        raw2, usage2 = llm.chat(
            cfg, system,
            user + "\n\n重要：请严格输出合法完整的 JSON，不要有任何多余文字，不要截断。",
            max_tokens=min(max_tokens * 2, 16384), temperature=0.0)
        usage = _merge_usage(usage, usage2)
        try:
            return llm.parse_json(raw2), usage
        except Exception:
            try:
                return llm.parse_json(_repair_json(raw2)), usage
            except Exception as last:
                raise JsonRetryError(
                    "%s: %s" % (type(last).__name__, last), usage) from first


def _judge_once(cfg, user):
    """跑一次判定，返回 (results, usage)。

    三级兜底都失败才抛 JudgeParseError。
    **绝不能因为模型吐了坏 JSON 就让整条核查崩掉** —— 评测里真踩到过，
    一条样本直接报错、白花前面所有的钱。由 judge() 接着降级成"无法判定"。
    """
    try:
        data, usage = _chat_json(cfg, STEP3_SYSTEM, user, 6144)
    except JsonRetryError as e:
        raise JudgeParseError(str(e), e.usage)
    return normalize(data.get("results") or []), usage


def judge(cfg, claims, votes=None):
    """第三步：把断言和分级后的证据交给模型判定。返回 (results列表, usage)。

    votes > 1 时跑多次、按多数票取结论（self-consistency）。
    这是为了对付"同一份证据跑两次给两个答案"—— 实测确实会发生。
    平票时取最保守的一档（insufficient）。
    """
    blocks = []
    for i, c in enumerate(claims, 1):
        lines = ["【断言 %d】%s" % (i, c["claim"])]
        ev = c.get("evidence") or []
        if not ev:
            lines.append("（没有检索到任何结果）")
        for r in ev:
            tier = r.get("tier", sources.UNKNOWN)
            if r.get("tier_inferred"):
                tier += "(据标题推断)"
            # 标出这条看的是原文还是搜索摘要 —— 摘要可能漏掉关键限定词，
            # 模型据此知道该不该对"没提到例外"下太强的结论。
            kind = "全文" if r.get("fulltext") else "仅摘要"
            lines.append("- [%s|%s] 标题：%s\n  网址：%s\n  内容：%s"
                         % (tier, kind, r.get("title", ""), r.get("url", ""), r.get("content", "")))
        blocks.append("\n".join(lines))

    user = "待核查的断言与证据：\n\n" + "\n\n".join(blocks)

    try:
        n = int(votes if votes is not None else (cfg.get("JUDGE_VOTES") or 1))
    except Exception:
        n = 1
    n = max(1, min(n, 9))

    runs, usages = [], []
    for _ in range(n):
        try:
            res, u = _judge_once(cfg, user)
        except JudgeParseError as e:
            # 模型吐了坏 JSON，三级兜底都没救回来。
            # 这里**绝不往上抛** —— 一条样本崩掉会浪费前面所有的检索和模型调用。
            # 老实说"无法判定"才是这个工具该有的态度（查不到就直说，不猜）。
            usages.append(getattr(e, "usage", {}))
            runs.append([{
                "claim": c["claim"],
                "verdict": "insufficient",
                "confidence": 0.0,
                "reason": "模型输出无法解析（已重试并尝试修复），不作判定：%s" % e,
                "sources": [],
            } for c in claims])
            continue
        runs.append(res)
        usages.append(u)

    usage = usages[0]
    for u in usages[1:]:
        usage = _merge_usage(usage, u)
    return _vote(runs), usage


def _vote(runs):
    """按断言位置对齐，逐条取多数票。"""
    if not runs:
        return []
    base = runs[0]
    if len(runs) == 1:
        return base

    out = []
    for i, r in enumerate(base):
        counts, confs = {}, []
        for run in runs:
            if i >= len(run):
                continue
            v = run[i].get("verdict")
            counts[v] = counts.get(v, 0) + 1
            confs.append(float(run[i].get("confidence") or 0))

        if counts:
            top = max(counts.values())
            winners = sorted(v for v, c in counts.items() if c == top)
            winner = winners[0] if len(winners) == 1 else (
                "insufficient" if "insufficient" in winners else winners[0])
        else:
            winner = r.get("verdict", "insufficient")

        merged = dict(r)
        merged["verdict"] = winner
        merged["confidence"] = (sum(confs) / len(confs)) if confs else r.get("confidence", 0)
        merged["votes"] = counts
        merged["vote_total"] = sum(counts.values())
        out.append(merged)
    return out


def _merge_usage(a, b):
    out = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        out[k] = int(a.get(k) or 0) + int(b.get(k) or 0)
    return out


def normalize(results):
    """把模型输出规整一下，防止非法 verdict 漏到下游。"""
    clean = []
    for r in results:
        if not isinstance(r, dict):
            continue
        v = (r.get("verdict") or "").strip().lower()
        if v not in VALID_VERDICTS:
            v = "insufficient"
        try:
            conf = float(r.get("confidence") or 0)
        except Exception:
            conf = 0.0
        clean.append({
            "claim": (r.get("claim") or "").strip(),
            "verdict": v,
            "confidence": max(0.0, min(1.0, conf)),
            "reason": (r.get("reason") or "").strip(),
            "sources": [s for s in (r.get("sources") or []) if isinstance(s, dict)],
        })
    return clean


def verify_sources(results, claims):
    """第四步（硬闸门）：模型引用的网址必须真的出现在检索结果里。

    模型偶尔会"顺手"编出一个看起来很像的网址。这里逐条比对，
    老老实实剔除并记录下来，让用户在界面上看得见。
    """
    allowed = set()
    for c in claims:
        for r in c.get("evidence") or []:
            if r.get("url"):
                allowed.add(r["url"].strip())

    for res in results:
        kept, dropped = [], []
        for s in res.get("sources") or []:
            url = (s.get("url") or "").strip()
            if url and url in allowed:
                kept.append(s)
            else:
                dropped.append(s)
        res["sources"] = kept
        res["dropped_sources"] = dropped
    return results


def overall_verdict(results):
    """把多条断言的判定汇总成一个「总判定」。

    这里踩过一个坑，值得记下来：
    最初写的是"只要有任一条不符，整段就判不符"（取最坏）。
    评测时发现，一段"大部分属实、只有一句说过头"的话会被盖上
    🔴「与事实不符」的章 —— 用户可能因此把真话一起扔掉。
    所以现在把「部分属实」单独作为一档。
    """
    verdicts = [r.get("verdict") for r in results]
    if not verdicts:
        return "insufficient"

    # refuted 优先于 mixed：只要有一条断言被明确否证，整条消息就不该被当成可信。
    # （比如"紫菜撕不烂"确实是事实，但"所以是塑料袋做的"是假的 —— 这条消息的
    #   结论是错的，标题就该是"与事实不符"，而不是"部分属实"。）
    if "refuted" in verdicts:
        return "refuted"
    if "mixed" in verdicts:
        return "mixed"          # 主张成立但措辞过头
    if all(v == "supported" for v in verdicts):
        return "supported"
    return "insufficient"       # 其余情况（含"有可信但有的查不到"）


def summarize_usage(usages):
    total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for u in usages:
        for k in total:
            total[k] += int(u.get(k) or 0)
    return total


def run(cfg, text, on_progress=None, use_cache=True):
    """把整条流水线跑一遍，返回 (claims, results, usages)。

    on_progress 收到 (阶段名, 附加信息)，方便界面显示进度。
    命中结果缓存时直接返回上次的结论，不花一分钱。
    """
    def say(stage, info=""):
        if on_progress:
            on_progress(stage, info)

    try:
        days = float(cfg.get("CACHE_DAYS", "7") or 0)
    except Exception:
        days = 7.0

    key = _result_key(cfg, text)
    if use_cache and days > 0:
        hit = _load_result_cache().get(key)
        if hit and time.time() - hit.get("t", 0) < days * 86400:
            say("cache_hit")
            return (copy.deepcopy(hit.get("claims", [])),
                    copy.deepcopy(hit.get("results", [])),
                    hit.get("usages", []))

    say("split")
    try:
        claims, u1 = extract_claims(cfg, text)
    except ClaimParseError as e:
        # 第一步吐了坏 JSON，重试 + 修复都没救回来。
        # **绝不往上抛** —— 抛出去整条核查就白跑了（评测里白花过一条样本的钱），
        # 而这只是模型的一次口误。老实说"这条没法判"才是这个工具该有的态度，
        # 与 judge 的降级策略保持一致：查不到就直说，不猜。
        return [], [{
            "claim": text,
            "verdict": "insufficient",
            "confidence": 0.0,
            "reason": "拆断言这一步模型输出无法解析（已重试并尝试修复），不作判定：%s" % e,
            "sources": [],
        }], [getattr(e, "usage", {})]
    if not claims:
        return [], [], [u1]

    say("search")
    gather_evidence(cfg, claims, on_progress=lambda c, q: say("searching", q))

    say("judge")
    results, u2 = judge(cfg, claims)

    verify_sources(results, claims)

    if use_cache and days > 0:
        cache = _load_result_cache()
        cache[key] = {"t": time.time(), "claims": claims,
                      "results": results, "usages": [u1, u2]}
        _save_result_cache()

    return claims, results, [u1, u2]
