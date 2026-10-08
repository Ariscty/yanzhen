// 验真 · 设置页逻辑
const FIELDS = ['deepseekKey', 'model', 'baseUrl', 'provider', 'tavilyKey', 'bochaKey',
  'maxClaims', 'maxResults', 'maxEvidence', 'newsDays', 'judgeVotes', 'cacheDays',
  'fulltext', 'fulltextMax', 'fulltextChars', 'fulltextTiers',
  'factCheckDomains', 'excludeDomains'];

const NUMERIC = ['maxClaims', 'maxResults', 'maxEvidence', 'newsDays',
  'judgeVotes', 'cacheDays', 'fulltext', 'fulltextMax', 'fulltextChars'];

const DEFAULTS = {
  deepseekKey: '',
  model: 'deepseek-flash',
  baseUrl: 'https://api.deepseek.com',
  provider: 'tavily',
  tavilyKey: '',
  bochaKey: '',
  maxClaims: 3,
  maxResults: 4,
  maxEvidence: 6,
  newsDays: 30,
  judgeVotes: 1,
  cacheDays: 7,
  fulltext: 1,
  fulltextMax: 3,
  fulltextChars: 3000,
  fulltextTiers: 'A,B',
  factCheckDomains: 'piyao.org.cn,kepuchina.cn,fact.qq.com',
  excludeDomains: 'baijiahao.baidu.com,csdn.net,jianshu.com,sohu.com,163.com,toutiao.com,ifeng.com',
};

const $ = (id) => document.getElementById(id);

function say(text, cls) {
  const el = $('msg');
  el.textContent = text;
  el.className = cls || '';
}

async function load() {
  const cfg = Object.assign({}, DEFAULTS, await chrome.storage.local.get(FIELDS));
  for (const f of FIELDS) {
    const el = $(f);
    if (el) el.value = cfg[f];
  }
}

async function save() {
  const cfg = {};
  for (const f of FIELDS) {
    const el = $(f);
    if (!el) continue;
    let v = el.value.trim();
    if (NUMERIC.includes(f)) {
      v = Number(v);
      if (!isFinite(v)) v = DEFAULTS[f];
    }
    cfg[f] = v;
  }
  if (!cfg.model) cfg.model = DEFAULTS.model;
  if (!cfg.baseUrl) cfg.baseUrl = DEFAULTS.baseUrl;
  await chrome.storage.local.set(cfg);
  say('已保存 ✓', 'ok');
  setTimeout(() => say(''), 2500);
}

async function test() {
  say('测试中…');
  const cfg = {};
  for (const f of FIELDS) if ($(f)) cfg[f] = $(f).value.trim();
  if (!cfg.deepseekKey) { say('先填 DeepSeek key', 'bad'); return; }

  // 直接在这里发请求，先保存再测，避免后台拿到旧配置
  await save();
  try {
    const base = (cfg.baseUrl || DEFAULTS.baseUrl).replace(/\/$/, '');
    const res = await fetch(base + '/models', {
      headers: { Authorization: 'Bearer ' + cfg.deepseekKey },
    });
    if (!res.ok) {
      say(`模型接口返回 HTTP ${res.status}`, 'bad');
      return;
    }
    const data = await res.json();
    const names = (data.data || []).map((m) => m.id).join('、');
    say(`模型连接正常，可用模型：${names}`, 'ok');
  } catch (e) {
    say('模型连接失败：' + (e.message || e), 'bad');
  }
}

$('save').addEventListener('click', save);
$('test').addEventListener('click', test);
load();
