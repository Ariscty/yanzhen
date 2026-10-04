// 验真 · 内核（由 Python 版 check.py / sources.py / search.py 翻译而来）
//
// 这一层刻意不碰任何浏览器 API，纯逻辑：
//   - 想搬到别的地方（比如网页版、Node 脚本）不用改
//   - 方便单独调试
// 浏览器相关的事情（storage、消息、渲染）都留给 background.js 和 content.js。

// ⚠️ 改提示词或改流程之后必须 +1（检索策略也算「流程」）。
//    这个值和 Python 版 check.py 的 PROMPT_VERSION 必须保持一致。
//    v8：多了一路「辟谣 / fact check」检索，检索改为并发发出。
//    v9：判定提示词加第 11 条 —— A/B 级来源明确冲突且无更高层级裁决时，必须判 insufficient。
export const PROMPT_VERSION = '9';

// ============================================================ 来源分级
// 中文互联网上，「一份政府公告」和「一条自媒体转述」是完全不同强度的证据。
// 模型自己分不清，所以我们替它分好级，再明确规定各级能支撑什么结论。
export const TIER = {
  A: 'A 官方一手',
  P: 'A 当事方官网',
  B: 'B 权威媒体',
  C: 'C 专业机构',
  D: 'D 自媒体百科',
  U: '未分级',
};

const A_SUFFIXES = ['.gov.cn', '.gov.hk', '.gov.tw', '.gov',
  '.edu.cn', '.edu.hk', '.ac.cn', '.ac.uk', '.mil.cn', '.org.cn',
  // 各国政府
  '.gov.uk', '.gov.au', '.govt.nz', '.gov.sg', '.gov.my', '.gov.in',
  '.gov.br', '.gov.za', '.gov.ie', '.gob.es', '.gouv.fr', '.go.jp',
  '.go.kr', '.admin.ch', '.bund.de', '.overheid.nl',
  // 国际组织
  '.europa.eu', '.un.org', '.who.int', '.worldbank.org', '.imf.org',
  '.oecd.org', '.wto.org', '.undp.org', '.unicef.org', '.iaea.org'];
// 有些公立机构不用 .gov.cn（省级疾控用 sccdc.cn 这类）
const A_EXTRA = ['cdc.cn', 'chinacdc.cn', 'nhs.uk', 'ipcc.ch', 'nap.edu',
  'esa.int', 'cern.ch', 'si.edu',
  'iso.org', 'ieee.org', 'ietf.org', 'w3.org', 'ansi.org'];
// 「当事方官网」：机构/企业自己的站点。
// ⚠️ 和 A 级官方一手不完全一样：
//    证明「关于该机构自身的客观事实」（成立时间、发布了什么）→ 一手来源 ✅
//    证明「效果更好/更安全/行业第一」→ 不算证据 ❌（那是自我宣传）
// 这个限制写在提示词里，模型会照着执行。
const PARTY_DOMAINS = [
  'openai.com', 'anthropic.com', 'deepmind.google', 'blog.google',
  'microsoft.com', 'apple.com', 'google.com', 'meta.com', 'nvidia.com',
  'intel.com', 'amd.com', 'ibm.com', 'amazon.com', 'tesla.com',
  'samsung.com', 'sony.com', 'huawei.com', 'xiaomi.com', 'oppo.com',
  'alibabagroup.com', 'tencent.com', 'bytedance.com', 'baidu.com',
  'jd.com', 'meituan.com', 'bilibili.com',
  'pfizer.com', 'modernatx.com', 'jnj.com', 'roche.com', 'novartis.com',
  'astrazeneca.com', 'sinopharm.com', 'coca-cola.com', 'pepsico.com',
  'nestle.com', 'unilever.com', 'toyota.com', 'volkswagen.com',
  'bmw.com', 'mercedes-benz.com', 'boeing.com', 'airbus.com', 'siemens.com',
  'linuxfoundation.org', 'apache.org', 'mozilla.org'];
const B_DOMAINS = [
  // 中文
  'xinhuanet.com', 'news.cn', 'people.com.cn', 'peopleapp.com',
  'cctv.com', 'cntv.cn', 'cnr.cn', 'cri.cn', 'china.com.cn', 'chinanews.com.cn',
  'chinanews.com', 'gmw.cn', 'chinadaily.com.cn', 'thepaper.cn', 'yicai.com',
  'caixin.com', 'stcn.com', 'cnstock.com', 'bjnews.com.cn', 'ynet.com',
  'nbd.com.cn', 'jiemian.com', 'cyol.com', 'huanqiu.com', 'globaltimes.cn',
  'ce.cn', 'stdaily.com', 'kepu.gov.cn', 'guancha.cn', 'oeeee.com',
  '21jingji.com', 'caijing.com.cn', 'southcn.com', 'qstheory.cn',
  // 国际主流媒体
  'bbc.com', 'bbc.co.uk', 'reuters.com', 'apnews.com', 'afp.com',
  'nytimes.com', 'washingtonpost.com', 'wsj.com', 'theguardian.com',
  'economist.com', 'ft.com', 'bloomberg.com', 'time.com', 'npr.org',
  'pbs.org', 'cnn.com', 'nbcnews.com', 'cbsnews.com', 'abcnews.go.com',
  'politico.com', 'axios.com', 'thehill.com', 'foreignpolicy.com',
  'aljazeera.com', 'dw.com', 'nhk.or.jp', 'asahi.com', 'yomiuri.co.jp',
  'scmp.com', 'straitstimes.com', 'abc.net.au', 'cbc.ca',
  'lemonde.fr', 'spiegel.de', 'zeit.de', 'faz.net', 'elpais.com',
  'corriere.it', 'lefigaro.fr',
  // 国际科学媒体
  'science.org', 'nature.com', 'scientificamerican.com',
  'newscientist.com', 'nationalgeographic.com', 'statnews.com', 'sciencemag.org',
  // 国际科技 / 商业媒体
  'techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com',
  'engadget.com', 'zdnet.com', 'cnet.com', 'businessinsider.com',
  'cnbc.com', 'forbes.com', 'fortune.com', 'usnews.com',
  'latimes.com', 'bostonglobe.com', 'seattletimes.com',
  // 国际科普媒体
  'sciencedaily.com', 'phys.org', 'quantamagazine.org', 'theconversation.com',
  'livescience.com', 'space.com', 'smithsonianmag.com', 'sciencefocus.com',
  'howstuffworks.com', 'popsci.com', 'sciencealert.com', 'iflscience.com',
  // 各国主流媒体（多国覆盖）
  'france24.com', 'rfi.fr', 'euronews.com', 'independent.co.uk',
  'telegraph.co.uk', 'thetimes.co.uk', 'globalnews.ca', 'smh.com.au',
  'theage.com.au', 'irishtimes.com', 'nzherald.co.nz', 'japantimes.co.jp',
  'koreaherald.com', 'thehindu.com', 'timesofindia.com',
  'haaretz.com', 'folha.uol.com.br', 'clarin.com'];
const C_DOMAINS = [
  'kepuchina.cn', 'kexuejia.cn', 'sciencenet.cn', 'guokr.com',
  'dxy.com', 'medsci.cn', 'haodf.com', 'cma.org.cn', 'cnki.net', 'cas.cn',
  'cae.cn',
  // 国际事实核查机构
  'snopes.com', 'politifact.com', 'factcheck.org', 'fullfact.org',
  'healthfeedback.org', 'sciencefeedback.co', 'climatefeedback.org',
  'mygopen.com', 'tfc-taiwan.org.tw', 'rumorsline.com',
  // 国际医疗 / 学术
  'cochranelibrary.com', 'mayoclinic.org', 'health.harvard.edu',
  'pubmed.ncbi.nlm.nih.gov', 'thelancet.com', 'bmj.com', 'jamanetwork.com',
  'nejm.org', 'cell.com', 'pnas.org', 'arxiv.org'];
const D_DOMAINS = ['weibo.com', 'weixin.qq.com', 'mp.weixin.qq.com', 'zhihu.com',
  'baijiahao.baidu.com', 'baike.baidu.com', 'wikipedia.org', 'toutiao.com',
  'sohu.com', '163.com', 'qq.com', 'sina.com.cn', 'ifeng.com', 'jianshu.com',
  'csdn.net', 'douyin.com', 'xiaohongshu.com', 'bilibili.com',
  'tieba.baidu.com', 'douban.com', 'xueqiu.com', 'youtube.com', 'facebook.com',
  'x.com', 'twitter.com', 'reddit.com', 'medium.com', 'quora.com',
  'blogspot.com', 'wordpress.com', 'substack.com', 'tiktok.com'];
// 精确域名覆盖：优先级最高。用来处理"平台子域其实是专业栏目"。
// 例：fact.qq.com 是腾讯较真（事实核查栏目），不该跟着 qq.com 一起算 D 级。
const EXACT_OVERRIDES = {
  'fact.qq.com': 'C 专业机构',
  'news.qq.com': 'B 权威媒体',
  'piyao.org.cn': 'A 官方一手',
  'www.piyao.org.cn': 'A 官方一手',
  'www.mayoclinic.org': 'C 专业机构',
};

// 域名判断不出来时的兜底：标题里出现这些词，基本是公立机构页面。
// 刻意不放「大学/医院/研究院」—— 新闻标题里经常出现（「某大学研究发现…」），
// 那是媒体报道，不是一手来源。
const OFFICIAL_HINTS = ['疾病预防控制中心', '疾控中心', '卫生健康委员会', '卫健委',
  '人民政府', '市场监督管理局', '药品监督管理局', '监督管理局', '应急管理局',
  '应急管理厅', '公安局', '公安厅', '人民法院', '人民检察院', '教育局',
  '教育厅', '民政厅', '财政厅', '管理局', '委员会'];

function hostOf(url) {
  try { return new URL(url).hostname.toLowerCase().replace(/^\./, ''); }
  catch (e) { return ''; }
}

function matchesAny(host, list) {
  return list.some((d) => host === d || host.endsWith('.' + d));
}

export function tierOf(url) {
  const host = hostOf(url);
  if (!host) return [TIER.U, ''];

  if (EXACT_OVERRIDES[host]) return [EXACT_OVERRIDES[host], host];   // 精确覆盖优先

  for (const suf of A_SUFFIXES) {
    if (host === suf.replace(/^\./, '') || host.endsWith(suf)) return [TIER.A, host];
  }
  if (matchesAny(host, A_EXTRA)) return [TIER.A, host];
  if (matchesAny(host, D_DOMAINS)) return [TIER.D, host];   // D 先判，免得平台子域误判
  if (matchesAny(host, PARTY_DOMAINS)) return [TIER.P, host];
  if (matchesAny(host, B_DOMAINS)) return [TIER.B, host];
  if (matchesAny(host, C_DOMAINS)) return [TIER.C, host];
  return [TIER.U, host];
}

export function annotate(item) {
  let [level, host] = tierOf(item.url || '');
  item.tier = level;
  item.tierHost = host;
  item.tierInferred = false;

  if (level === TIER.U) {
    const title = item.title || '';
    const hit = OFFICIAL_HINTS.find((h) => title.includes(h));
    if (hit) {
      item.tier = TIER.A;
      item.tierInferred = true;
      item.tierHint = hit;
    }
  }
  return item;
}

export function tierLetter(level) {
  if (!level || level === TIER.U) return '?';
  return level.split(' ')[0];
}

export function tierSummary(tiers) {
  // 显示时按首字母归并：A 官方一手 与 A 当事方官网 都显示成 A
  //（用户只看强弱，两者更细的区别留给模型判断）
  const counts = {};
  for (const t of tiers) {
    const letter = tierLetter(t);
    counts[letter] = (counts[letter] || 0) + 1;
  }
  const order = ['A', 'B', 'C', 'D', '?'];
  const parts = order.filter((k) => counts[k]).map((k) => `${k}×${counts[k]}`);
  return parts.length ? parts.join(' ') : '无';
}

export function hasStrongTiers(tiers) {
  return tiers.some((t) => t === TIER.A || t === TIER.P || t === TIER.B);
}

// ============================================================ 提示词
function step1System(maxClaims) {
  return `你是事实核查助手的第一步：拆分断言。

把用户给的文字拆成可以独立核查的「事实性断言」。规则：
1. 最多拆成 ${maxClaims} 条，优先挑最关键、最具体的。
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
{"claims":[{"claim":"断言原文","query":"中文关键词","query_en":"english keywords","time_sensitive":false}]}`;
}

const STEP3_SYSTEM = `你是事实核查的第二步：基于证据下结论。

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

其他要求：
- sources 里的 url 只能从【证据】中原样复制，**禁止编造任何网址**。
- reason 用一句中文说清依据，不超过 60 字，并点出关键来源属于哪一级；
  证据互相冲突时，必须在 reason 里点出冲突双方。
- 有明确 A 级一手来源时，confidence 可以给到 0.85 以上；仅靠 B 级给 0.6~0.8；
  只靠 C 级或未分级不超过 0.6；证据互相矛盾时不要超过 0.6。

只输出 JSON，不要任何解释：
{"results":[{"claim":"断言原文","verdict":"supported|refuted|insufficient|mixed","confidence":0.0,"reason":"判定依据","sources":[{"url":"网址","title":"标题"}]}]}`;

export const VERDICT_LABEL = {
  supported: '可信',
  refuted: '与事实不符',
  insufficient: '证据不足',
  mixed: '部分属实',
};

// ============================================================ 底层调用
function fetchTimeout(url, options, ms) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, Object.assign({}, options, { signal: ctrl.signal }))
    .finally(() => clearTimeout(timer));
}

function parseJson(text) {
  let t = (text || '').trim();
  if (t.startsWith('```')) {
    const parts = t.split('```');
    if (parts.length > 1) t = parts[1];
    if (t.toLowerCase().startsWith('json')) t = t.slice(4);
  }
  t = t.trim();
  try { return JSON.parse(t); } catch (e) { /* 继续尝试截取 */ }
  const s = t.indexOf('{');
  const e2 = t.lastIndexOf('}');
  if (s >= 0 && e2 > s) return JSON.parse(t.slice(s, e2 + 1));
  throw new Error('模型返回的内容不是合法 JSON');
}

async function callDeepSeek(cfg, system, user, opts) {
  const o = Object.assign({ json: true, maxTokens: 6144, temperature: 0 }, opts || {});
  const body = {
    model: cfg.model,
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    temperature: o.temperature,
    max_tokens: o.maxTokens,
    stream: false,
  };
  if (o.json) body.response_format = { type: 'json_object' };

  let budget = o.maxTokens;
  let lastErr = null;
  // V4.1 是带思考过程的模型，思考也占用 max_tokens。
  // 思考一长，正式回答会被挤成空字符串 —— 检测到就加大预算重试。
  for (let i = 0; i < 3; i++) {
    body.max_tokens = budget;
    const res = await fetchTimeout(cfg.baseUrl.replace(/\/$/, '') + '/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + cfg.deepseekKey,
      },
      body: JSON.stringify(body),
    }, 180000);

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`DeepSeek 返回 HTTP ${res.status}：${txt.slice(0, 300)}`);
    }
    const data = await res.json();
    const text = (data.choices && data.choices[0] && data.choices[0].message
      && data.choices[0].message.content) || '';
    const usage = data.usage || {};
    if (!text.trim()) {
      const think = (usage.completion_tokens_details || {}).reasoning_tokens;
      lastErr = new Error(`模型返回空内容（max_tokens=${budget} 被思考过程耗尽，思考用了 ${think} 个 token）`);
      budget = Math.min(budget * 2, 16384);
      continue;
    }
    return { text, usage };
  }
  throw lastErr || new Error('模型调用失败');
}

// ---------------------------------------------------------- 搜索适配器
// 不绑定任何一家：用户填哪家的 key 就用哪家（与命令行版同一套设计）
async function tavilySearch(cfg, query, limit, newsDays) {
  if (!cfg.tavilyKey) throw new Error('没填 Tavily key —— 去 https://app.tavily.com 申请（每月 1000 次免费）');
  const body = {
    api_key: cfg.tavilyKey, query, max_results: limit, search_depth: 'basic',
  };
  // newsDays 有值时走新闻模式（topic=news + days=N）：只返回最近 N 天的新闻，结果带发布时间
  if (newsDays) {
    body.topic = 'news';
    body.days = Number(newsDays);
  }
  const res = await fetchTimeout('https://api.tavily.com/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, 40000);
  if (!res.ok) throw new Error(`Tavily 返回 HTTP ${res.status}：${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  return (data.results || []).map((r) => {
    const item = {
      title: r.title || '', url: r.url || '', content: (r.content || '').slice(0, 1200),
    };
    const pub = r.published_date || r.published;
    if (pub) item.published = pub;
    return item;
  });
}

async function bochaSearch(cfg, query, limit, newsDays) {
  if (!cfg.bochaKey) throw new Error('没填博查 key');
  const body = { query, count: limit, summary: true };
  if (newsDays) body.freshness = newsDays <= 7 ? 'oneWeek' : 'oneMonth';
  const res = await fetchTimeout(cfg.bochaEndpoint || 'https://api.bochaai.com/v1/web-search', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + cfg.bochaKey,
    },
    body: JSON.stringify(body),
  }, 40000);
  if (!res.ok) throw new Error(`博查返回 HTTP ${res.status}：${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  // 兼容几种可能的返回结构（这个适配器尚未实测验证）
  const pages = (((data.data || {}).webPages || {}).value)
    || ((data.webPages || {}).value)
    || ((data.data || {}).value) || [];
  return pages.slice(0, limit).map((it) => ({
    title: it.name || it.title || '',
    url: it.url || '',
    content: (it.summary || it.snippet || it.content || '').slice(0, 1500),
  }));
}

async function mockSearch(cfg, query, limit, newsDays) {
  const tag = newsDays ? '（新闻模式）' : '';
  return [
    {
      title: `[模拟结果]${tag} 关于「${query}」的示例网页`,
      url: 'https://example.com/mock-1',
      content: '这是模拟出来的检索片段，用于验证流程。它不是真实网页，结论不可当真。',
    },
    {
      title: `[模拟结果]${tag} 另一篇相关文章`,
      url: 'https://example.com/mock-2',
      content: '同样是一条模拟结果。要得到真实结论，请在设置里选 tavily 或 bocha 并填 key。',
    },
  ].slice(0, limit);
}

export async function webSearch(cfg, query, limit, newsDays) {
  const p = (cfg.provider || 'tavily').toLowerCase();
  if (p === 'tavily') return tavilySearch(cfg, query, limit, newsDays);
  if (p === 'bocha') return bochaSearch(cfg, query, limit, newsDays);
  if (p === 'mock') return mockSearch(cfg, query, limit, newsDays);
  throw new Error('未知的搜索来源：' + p);
}

// 证据取舍：按来源等级排序，A/B 级先占位置，弱来源被挤掉。
// 这是"双语搜索"能把 token 成本控制住的关键（候选变多，但保留数固定）。
const TIER_RANK = { 'A 官方一手': 0, 'A 当事方官网': 1, 'B 权威媒体': 2,
  'C 专业机构': 3, '未分级': 4, 'D 自媒体百科': 5 };

function pickEvidence(pool, cap) {
  const seen = new Set();
  const picked = [];
  const sorted = pool.slice().sort((a, b) => (TIER_RANK[a.tier] ?? 3) - (TIER_RANK[b.tier] ?? 3));
  for (const r of sorted) {
    const u = String(r.url || '').trim();
    if (!u || seen.has(u)) continue;
    seen.add(u);
    picked.push(r);
    if (picked.length >= cap) break;
  }
  return picked;
}

function normQuery(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, '');
}

// 给每条断言多配一路「辟谣 / fact check」检索。
// 事实核查类站点（中国互联网联合辟谣平台、腾讯较真、Snopes、FactCheck.org）
// 在搜索结果里本来就排得靠前，但**必须用对关键词**才能勾出来 ——
// 用断言原话去搜，往往搜到的还是原始谣言本身。
function factCheckQuery(c) {
  const q = String(c.query || c.claim || '').trim();
  if (!q) return '';
  return /[\u4e00-\u9fff]/.test(q) ? `${q} 辟谣 真相` : `${q} fact check`;
}

// ============================================================ 流水线
function normalize(results) {
  const ok = Object.keys(VERDICT_LABEL);
  return (results || []).filter((r) => r && typeof r === 'object').map((r) => {
    let v = String(r.verdict || '').trim().toLowerCase();
    if (!ok.includes(v)) v = 'insufficient';
    let conf = Number(r.confidence);
    if (!isFinite(conf)) conf = 0;
    return {
      claim: String(r.claim || '').trim(),
      verdict: v,
      confidence: Math.max(0, Math.min(1, conf)),
      reason: String(r.reason || '').trim(),
      sources: Array.isArray(r.sources) ? r.sources.filter((s) => s && typeof s === 'object') : [],
    };
  });
}

async function judgeOnce(cfg, user) {
  let raw;
  try {
    raw = await callDeepSeek(cfg, STEP3_SYSTEM, user, { maxTokens: 6144 });
  } catch (e) {
    throw e;
  }
  try {
    return { results: normalize(parseJson(raw.text).results), usage: raw.usage };
  } catch (e) {
    // 模型偶尔会吐出不完整的 JSON（回答一长就容易截断），重试一次
    const raw2 = await callDeepSeek(cfg, STEP3_SYSTEM,
      user + '\n\n重要：请严格输出合法完整的 JSON，不要有任何多余文字，不要截断。',
      { maxTokens: 8192 });
    return { results: normalize(parseJson(raw2.text).results), usage: raw2.usage };
  }
}

function vote(runs) {
  if (!runs.length) return [];
  if (runs.length === 1) return runs[0];
  const base = runs[0];
  return base.map((r, i) => {
    const counts = {};
    const confs = [];
    for (const run of runs) {
      if (i >= run.length) continue;
      const v = run[i].verdict;
      counts[v] = (counts[v] || 0) + 1;
      confs.push(Number(run[i].confidence) || 0);
    }
    const keys = Object.keys(counts);
    let winner = r.verdict;
    if (keys.length) {
      const top = Math.max(...keys.map((k) => counts[k]));
      const winners = keys.filter((k) => counts[k] === top).sort();
      // 平票时取最保守的一档
      winner = winners.length === 1 ? winners[0]
        : (winners.includes('insufficient') ? 'insufficient' : winners[0]);
    }
    const merged = Object.assign({}, r, {
      verdict: winner,
      confidence: confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : r.confidence,
      votes: counts,
      voteTotal: Object.values(counts).reduce((a, b) => a + b, 0),
    });
    return merged;
  });
}

export function verifySources(results, claims) {
  const allowed = new Set();
  for (const c of claims) for (const e of (c.evidence || [])) if (e.url) allowed.add(e.url.trim());
  for (const r of results) {
    const kept = [];
    const dropped = [];
    for (const s of (r.sources || [])) {
      const url = String(s.url || '').trim();
      if (url && allowed.has(url)) kept.push(s); else dropped.push(s);
    }
    r.sources = kept;
    r.droppedSources = dropped;
  }
  return results;
}

export function overallVerdict(results) {
  const vs = results.map((r) => r.verdict);
  if (!vs.length) return 'insufficient';
  // refuted 优先于 mixed：只要有一条断言被明确否证，整条消息就不该被当成可信。
  // （"紫菜撕不烂"是真，"所以是塑料袋做的"是假 —— 结论错，标题就该是"与事实不符"）
  if (vs.includes('refuted')) return 'refuted';
  if (vs.includes('mixed')) return 'mixed';
  if (vs.every((v) => v === 'supported')) return 'supported';
  return 'insufficient';
}

function mergeUsage(a, b) {
  const out = {};
  for (const k of ['prompt_tokens', 'completion_tokens', 'total_tokens']) {
    out[k] = (Number(a[k]) || 0) + (Number(b[k]) || 0);
  }
  return out;
}

/** 主流程：拆断言 → 检索 → 分级 → 判定 → 校验引用 */
export async function checkText(cfg, text, onProgress) {
  const say = (stage, info) => { try { onProgress && onProgress(stage, info || ''); } catch (e) { /* 忽略 */ } };
  const usages = [];

  // 第一步：拆断言
  say('split');
  const s1 = await callDeepSeek(cfg, step1System(cfg.maxClaims), text, { maxTokens: 2048 });
  usages.push(s1.usage);
  let claims = (parseJson(s1.text).claims || []);
  claims = claims.filter((c) => c && String(c.claim || '').trim())
    .slice(0, cfg.maxClaims)
    .map((c) => ({
      claim: String(c.claim).trim(),
      query: String(c.query || c.claim).trim(),
      query_en: String(c.query_en || '').trim(),
      time_sensitive: !!c.time_sensitive,
    }));
  if (!claims.length) return { claims: [], results: [], usages };

  // 第二步：检索 + 来源分级
  // 每条断言最多搜四次：①中文关键词 ②英文关键词
  //                      ③辟谣/fact check ④涉及近期事件时走新闻模式
  // 这几路之间**没有任何依赖**，所以并发发出。
  // （原来是 claims × queries 两层 for + await，6~9 路串行，白等十几秒。）
  say('search');
  const jobs = [];
  claims.forEach((c, ci) => {
    const q = c.query || c.claim;
    const plan = [[q, null, '中文']];
    if (c.query_en && normQuery(c.query_en) !== normQuery(q)) {
      plan.push([c.query_en, null, '英文']);
    }
    const fq = factCheckQuery(c);
    if (fq && normQuery(fq) !== normQuery(q)
        && normQuery(fq) !== normQuery(c.query_en || '')) {
      plan.push([fq, null, '辟谣']);
    }
    if (c.time_sensitive && Number(cfg.newsDays) > 0) {
      plan.push([q, Number(cfg.newsDays), '新闻']);
    }
    c.queries = plan.map(([qq, , mode]) => `${mode}:${qq}`);
    plan.forEach(([qq, days, mode]) => jobs.push({ ci, q: qq, days, mode, err: '' }));
  });

  say('searching', `并发检索 ${jobs.length} 路…`);
  const got = new Array(jobs.length).fill(null);
  // 限并发 4：搜索服务有限流，一次全发出去容易吃 429
  const MAX_PARALLEL = 4;
  for (let i = 0; i < jobs.length; i += MAX_PARALLEL) {
    await Promise.all(jobs.slice(i, i + MAX_PARALLEL).map(async (j, k) => {
      const n = i + k;
      try {
        got[n] = (await webSearch(cfg, j.q, cfg.maxResults, j.days)).map(annotate);
      } catch (e) {
        j.err = String(e.message || e);
      }
    }));
  }
  // key / 权限问题直接抛，不要装作"证据不足"
  for (const j of jobs) {
    if (j.err && /key|HTTP 401|HTTP 403/i.test(j.err)) throw new Error(j.err);
  }
  // 按任务序号拼回证据池：pickEvidence 的排序是稳定的，
  // 不按序号回收的话，证据顺序会随完成顺序变化，结论就不可复现了。
  const pools = claims.map(() => []);
  jobs.forEach((j, n) => { for (const r of (got[n] || [])) pools[j.ci].push(r); });
  claims.forEach((c, i) => {
    c.evidence = pickEvidence(pools[i], Number(cfg.maxEvidence) || 6);
    const bad = jobs.find((j) => j.ci === i && j.err);
    if (bad) c.searchError = bad.err;
  });

  // 第三步：判定（可选多次取多数）
  say('judge');
  const blocks = claims.map((c, i) => {
    const lines = [`【断言 ${i + 1}】${c.claim}`];
    if (!(c.evidence || []).length) lines.push('（没有检索到任何结果）');
    for (const e of (c.evidence || [])) {
      const tier = e.tier + (e.tierInferred ? '(据标题推断)' : '');
      lines.push(`- [${tier}] 标题：${e.title}\n  网址：${e.url}\n  内容：${e.content}`);
    }
    return lines.join('\n');
  });
  const user = '待核查的断言与证据：\n\n' + blocks.join('\n\n');

  const n = Math.max(1, Math.min(9, Number(cfg.judgeVotes) || 1));
  const runs = [];
  for (let i = 0; i < n; i++) {
    const out = await judgeOnce(cfg, user);
    runs.push(out.results);
    usages.push(out.usage);
  }
  const results = vote(runs);

  verifySources(results, claims);

  // 顺手把来源等级算好挂在结果上。
  // 这样 content.js 只负责画界面，不用把分级规则再抄一遍
  //（content script 不能用 ES 模块 import，抄一遍迟早会两边不一致）。
  for (const r of results) {
    const tiers = (r.sources || []).map((s) => {
      const lv = tierOf(s.url)[0];
      s.tier = tierLetter(lv);
      return lv;
    });
    r.tierSummary = tierSummary(tiers);
    r.tierStrong = hasStrongTiers(tiers);
  }

  return { claims, results, usages };
}

export function totalTokens(usages) {
  return (usages || []).reduce((sum, u) => sum + (Number(u && u.total_tokens) || 0), 0);
}
