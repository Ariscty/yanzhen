# -*- coding: utf-8 -*-
"""来源分级：把检索到的网址分成 A / B / C / D 四级。

为什么要做这个？
中文互联网上，「一份政府公告」和「一条自媒体转述」是完全不同强度的证据。
模型自己分不清，很容易把自媒体当权威引用，然后给出一个自信满满的错误结论。

我们在这里替它把来源分好级，再在提示词里明确规定：
只有 A / B 级来源才能支撑「可信 / 与事实不符」的判定，
全是 D 级就只能说「证据不足」。
"""
import urllib.parse

A = "A 官方一手"
PARTY = "A 当事方官网"
B = "B 权威媒体"
C = "C 专业机构"
D = "D 自媒体百科"
UNKNOWN = "未分级"

# A 级：政府 / 公立机构 / 原始文件。用域名后缀判断，最稳。
A_SUFFIXES = (
    ".gov.cn", ".gov.hk", ".gov.tw", ".gov",
    ".edu.cn", ".edu.hk", ".ac.cn", ".ac.uk",
    ".mil.cn", ".org.cn",
    # 各国政府
    ".gov.uk", ".gov.au", ".govt.nz", ".gov.sg", ".gov.my", ".gov.in",
    ".gov.br", ".gov.za", ".gov.ie", ".gob.es", ".gouv.fr", ".go.jp",
    ".go.kr", ".admin.ch", ".bund.de", ".overheid.nl",
    # 国际组织
    ".europa.eu", ".un.org", ".who.int", ".worldbank.org", ".imf.org",
    ".oecd.org", ".wto.org", ".undp.org", ".unicef.org", ".iaea.org",
)

# A 级的补充白名单：有些公立机构不用 .gov.cn（如省级疾控用 sccdc.cn）
A_EXTRA_DOMAINS = (
    "cdc.cn", "chinacdc.cn", "nmpa.gov.cn", "samr.gov.cn",
    "nhs.uk",                    # 英国国家医疗服务体系
    "ipcc.ch", "nap.edu",        # 政府间气候变化专门委员会 / 美国国家科学院
    "esa.int", "cern.ch",        # 欧洲空间局 / 欧洲核子研究中心
    "si.edu",                    # 史密森学会
    "iso.org", "ieee.org",       # 国际标准组织
    "ietf.org", "w3.org", "ansi.org",   # 互联网/国家标准组织
)

# 「当事方官网」：机构/企业自己的站点。
# ⚠️ 它和 A 级官方一手**不完全一样**：
#    - 用来证明「关于该机构自身的客观事实」（成立时间、发布了什么、公告内容）→ 是一手来源 ✅
#    - 用来证明「效果好 / 更安全 / 行业第一」这类主张 → **不算证据** ❌（那是自己的宣传）
# 这个限制写在提示词里，模型会照着执行。
PARTY_DOMAINS = (
    # 科技 / 互联网
    "openai.com", "anthropic.com", "deepmind.google", "blog.google",
    "microsoft.com", "apple.com", "google.com", "meta.com", "nvidia.com",
    "intel.com", "amd.com", "ibm.com", "amazon.com", "tesla.com",
    "samsung.com", "sony.com", "huawei.com", "xiaomi.com", "oppo.com",
    "alibabagroup.com", "tencent.com", "bytedance.com", "baidu.com",
    "jd.com", "meituan.com", "bilibili.com",
    # 医药 / 消费 / 制造
    "pfizer.com", "modernatx.com", "jnj.com", "roche.com", "novartis.com",
    "astrazeneca.com", "sinopharm.com", "coca-cola.com", "pepsico.com",
    "nestle.com", "unilever.com", "toyota.com", "volkswagen.com",
    "bmw.com", "mercedes-benz.com", "boeing.com", "airbus.com", "siemens.com",
    # 标准 / 开源组织
    "linuxfoundation.org", "apache.org", "mozilla.org",
)

# 域名判断不出来时的兜底：标题里出现这些词，基本可以认定是公立机构页面。
# 刻意不放"大学/医院/研究院"这类词 —— 新闻标题里经常出现，
# 比如「某大学研究发现微波炉致癌」，那是媒体报道，不是一手来源。
OFFICIAL_HINTS = (
    "疾病预防控制中心", "疾控中心", "卫生健康委员会", "卫健委",
    "人民政府", "市场监督管理局", "药品监督管理局", "监督管理局",
    "应急管理局", "应急管理厅", "公安局", "公安厅", "人民法院",
    "人民检察院", "教育局", "教育厅", "民政厅", "财政厅",
    "管理局", "委员会",
)

# B 级：央媒 / 官方通讯社 / 正规媒体（中文 + 国际）
B_DOMAINS = (
    # ---- 中文 ----
    "xinhuanet.com", "news.cn", "people.com.cn", "peopleapp.com",
    "cctv.com", "cntv.cn", "cnr.cn", "cri.cn", "china.com.cn",
    "chinanews.com.cn", "chinanews.com", "gmw.cn", "chinadaily.com.cn",
    "thepaper.cn", "yicai.com", "caixin.com", "stcn.com", "cnstock.com",
    "bjnews.com.cn", "ynet.com", "nbd.com.cn", "jiemian.com",
    "cyol.com", "huanqiu.com", "globaltimes.cn", "ce.cn", "stdaily.com",
    "kepu.gov.cn", "guancha.cn", "oeeee.com", "21jingji.com",
    "caijing.com.cn", "southcn.com", "qstheory.cn",
    # ---- 国际主流媒体 ----
    "bbc.com", "bbc.co.uk", "reuters.com", "apnews.com", "afp.com",
    "nytimes.com", "washingtonpost.com", "wsj.com", "theguardian.com",
    "economist.com", "ft.com", "bloomberg.com", "time.com", "npr.org",
    "pbs.org", "cnn.com", "nbcnews.com", "cbsnews.com", "abcnews.go.com",
    "politico.com", "axios.com", "thehill.com", "foreignpolicy.com",
    "aljazeera.com", "dw.com", "nhk.or.jp", "asahi.com", "yomiuri.co.jp",
    "scmp.com", "straitstimes.com", "abc.net.au", "cbc.ca",
    "lemonde.fr", "spiegel.de", "zeit.de", "faz.net", "elpais.com",
    "corriere.it", "lefigaro.fr",
    # ---- 国际科技 / 商业媒体 ----
    "techcrunch.com", "theverge.com", "arstechnica.com", "wired.com",
    "engadget.com", "zdnet.com", "cnet.com", "businessinsider.com",
    "cnbc.com", "forbes.com", "fortune.com", "usnews.com",
    "latimes.com", "bostonglobe.com", "seattletimes.com",
    # ---- 国际科普媒体 ----
    "science.org", "nature.com", "scientificamerican.com",
    "newscientist.com", "nationalgeographic.com", "statnews.com",
    "sciencemag.org",
    "sciencedaily.com", "phys.org", "quantamagazine.org",
    "theconversation.com", "livescience.com", "space.com",
    "smithsonianmag.com", "sciencefocus.com", "howstuffworks.com",
    "popsci.com", "sciencealert.com", "iflscience.com",
    # ---- 各国主流媒体（多国覆盖）----
    "france24.com", "rfi.fr", "euronews.com", "independent.co.uk",
    "telegraph.co.uk", "thetimes.co.uk", "globalnews.ca", "smh.com.au",
    "theage.com.au", "irishtimes.com", "nzherald.co.nz", "straitstimes.com",
    "japantimes.co.jp", "koreaherald.com", "thehindu.com", "timesofindia.com",
    "haaretz.com", "folha.uol.com.br", "clarin.com", "elpais.com",
)

# C 级：科普 / 医疗 / 学术 / 事实核查机构
C_DOMAINS = (
    "kepuchina.cn", "kexuejia.cn", "sciencenet.cn", "guokr.com",
    "dxy.com", "medsci.cn", "haodf.com", "cma.org.cn", "cnki.net",
    "cas.cn", "cae.cn",
    # 国际事实核查机构
    "snopes.com", "politifact.com", "factcheck.org", "fullfact.org",
    "healthfeedback.org", "sciencefeedback.co", "climatefeedback.org",
    "mygopen.com", "tfc-taiwan.org.tw", "rumorsline.com",
    # 国际医疗 / 学术
    "cochranelibrary.com", "mayoclinic.org", "health.harvard.edu",
    "pubmed.ncbi.nlm.nih.gov", "thelancet.com", "bmj.com", "jamanetwork.com",
    "nejm.org", "cell.com", "pnas.org", "arxiv.org",
)

# D 级：平台内容 / 百科 / 转载，只能当线索
D_DOMAINS = (
    "weibo.com", "weixin.qq.com", "mp.weixin.qq.com", "zhihu.com",
    "baijiahao.baidu.com", "baike.baidu.com", "wikipedia.org",
    "toutiao.com", "sohu.com", "163.com", "qq.com", "sina.com.cn",
    "ifeng.com", "jianshu.com", "csdn.net", "douyin.com",
    "xiaohongshu.com", "bilibili.com", "tieba.baidu.com", "douban.com",
    "so.com", "hao123.com", "xueqiu.com", "youtube.com", "facebook.com",
    "x.com", "twitter.com", "reddit.com", "medium.com", "quora.com",
    "blogspot.com", "wordpress.com", "substack.com", "tiktok.com",
)

# 精确域名覆盖：优先级最高，用来处理"平台子域其实是专业栏目"这种情况。
# 例：fact.qq.com 是腾讯较真（事实核查栏目），不该跟着 qq.com 一起算 D 级。
EXACT_OVERRIDES = {
    "fact.qq.com": C,          # 腾讯较真
    "news.qq.com": B,          # 腾讯新闻（编辑部内容）
    "piyao.org.cn": A,         # 中国互联网联合辟谣平台
    "www.piyao.org.cn": A,
    "health.clevelandclinic.org": C,
    "www.mayoclinic.org": C,
}


def _domain(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""
    return host.lower().lstrip(".")


def tier_of(url):
    """返回 (等级, 说明)。等级是 A/B/C/D/未分级 中的字符串。"""
    host = _domain(url)
    if not host:
        return UNKNOWN, ""

    if host in EXACT_OVERRIDES:             # 精确覆盖优先
        return EXACT_OVERRIDES[host], host

    for suf in A_SUFFIXES:
        if host == suf.lstrip(".") or host.endswith(suf):
            return A, host

    for d in A_EXTRA_DOMAINS:
        if host == d or host.endswith("." + d):
            return A, host

    for d in D_DOMAINS:                     # D 先于 B/C 判断，避免平台子域误判
        if host == d or host.endswith("." + d):
            return D, host

    for d in PARTY_DOMAINS:                 # 当事方官网（用途有限制，见提示词）
        if host == d or host.endswith("." + d):
            return PARTY, host

    for d in B_DOMAINS:
        if host == d or host.endswith("." + d):
            return B, host

    for d in C_DOMAINS:
        if host == d or host.endswith("." + d):
            return C, host

    return UNKNOWN, host


def annotate(evidence):
    """给一条证据打上来源等级标签。

    域名分不出来时，看标题里有没有公立机构的标志性词（兜底规则），
    命中的话算 A 级，但会打上 tier_inferred 标记，方便复核。
    """
    lvl, host = tier_of(evidence.get("url", ""))
    evidence["tier_inferred"] = False

    if lvl == UNKNOWN:
        title = evidence.get("title") or ""
        hit = next((h for h in OFFICIAL_HINTS if h in title), None)
        if hit:
            lvl = A
            evidence["tier_inferred"] = True
            evidence["tier_hint"] = hit

    evidence["tier"] = lvl
    evidence["tier_host"] = host
    return evidence


def summary(evidence_list):
    """统计一组证据的等级分布，返回形如 'A×2 B×1 D×2' 的字符串。"""
    return summary_tiers([e.get("tier", UNKNOWN) for e in evidence_list])


def summary_tiers(tier_list):
    """统计一组等级字符串的分布。显示时按首字母归并
    （A 官方一手 与 A 当事方官网 都显示成 A，用户只看强弱；区分留给模型判断）。"""
    counts = {}
    for t in tier_list:
        letter = (t or "?").split()[0]
        counts[letter] = counts.get(letter, 0) + 1
    if not counts:
        return "无"
    order = ["A", "B", "C", "D", "未分级"]
    return " ".join("%s×%d" % (k, counts[k]) for k in order if k in counts)


def tiers_of_urls(urls):
    """把一组网址转成等级列表。"""
    return [tier_of(u)[0] for u in urls]


def has_strong(evidence_list):
    """这组证据里有没有 A / A当事方 / B 级来源。"""
    return any(e.get("tier") in (A, PARTY, B) for e in evidence_list)


def has_strong_tiers(tier_list):
    return any(t in (A, PARTY, B) for t in tier_list)
