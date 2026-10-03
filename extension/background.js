// 验真 · 后台（Service Worker）
// 职责：接快捷键/右键菜单 → 取选中文字 → 跑内核 → 把结果发回页面卡片
import { checkText, overallVerdict, totalTokens, VERDICT_LABEL } from './core.js';

const DEFAULTS = {
  deepseekKey: '',
  model: 'deepseek-flash',
  baseUrl: 'https://api.deepseek.com',
  provider: 'tavily',
  tavilyKey: '',
  bochaKey: '',
  bochaEndpoint: 'https://api.bochaai.com/v1/web-search',
  maxClaims: 3,
  maxResults: 4,      // 每种语言取几条（中文一遍、英文一遍）
  maxEvidence: 6,     // 每条断言最终保留几条证据（按来源等级取舍）
  newsDays: 30,       // 近期事件追加新闻搜索的时间范围；0 = 关闭
  judgeVotes: 1,
  cacheDays: 7,
};

async function getConfig() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const cfg = Object.assign({}, DEFAULTS, stored);
  for (const k of ['maxClaims', 'maxResults', 'maxEvidence', 'newsDays',
    'judgeVotes', 'cacheDays']) {
    cfg[k] = Number(cfg[k]);
    if (!isFinite(cfg[k])) cfg[k] = DEFAULTS[k];
  }
  return cfg;
}

function checkConfig(cfg) {
  const problems = [];
  if (!cfg.deepseekKey) problems.push('没填 DeepSeek API Key');
  if (cfg.provider === 'tavily' && !cfg.tavilyKey) problems.push('没填 Tavily API Key');
  if (cfg.provider === 'bocha' && !cfg.bochaKey) problems.push('没填博查 API Key');
  return problems;
}

// ---------------------------------------------------------------- 缓存
// 缓存整条核查结果：同一段文字重复查询结果一致，第二次还免费。
// （命令行版踩过的坑：拆断言的措辞每次略不同 → 搜索关键词变 → 结论翻转）
function hashKey(cfg, text) {
  const norm = (text || '').toLowerCase().replace(/[\s，,。.、·:：;；!！?？"'“”‘’()（）[\]【】\-—_/\\]/g, '');
  const raw = [6, norm, cfg.provider, cfg.maxClaims, cfg.maxResults, cfg.maxEvidence,
    cfg.newsDays, cfg.judgeVotes, cfg.model].join('|');
  let h = 5381;
  for (let i = 0; i < raw.length; i++) h = ((h << 5) + h + raw.charCodeAt(i)) | 0;
  return 'rc:' + (h >>> 0).toString(36);
}

async function readCache(cfg, text) {
  if (!(cfg.cacheDays > 0)) return null;
  const key = hashKey(cfg, text);
  const got = await chrome.storage.local.get(key);
  const hit = got[key];
  if (!hit) return null;
  if (Date.now() - hit.t > cfg.cacheDays * 86400000) return null;
  return hit;
}

async function writeCache(cfg, text, payload) {
  if (!(cfg.cacheDays > 0)) return;
  const key = hashKey(cfg, text);
  const obj = {};
  obj[key] = Object.assign({ t: Date.now() }, payload);
  await chrome.storage.local.set(obj);
  // 顺手清理过期项，免得 storage 越堆越大
  const all = await chrome.storage.local.get(null);
  const stale = Object.keys(all).filter((k) => k.startsWith('rc:')
    && Date.now() - (all[k].t || 0) > cfg.cacheDays * 86400000);
  if (stale.length) await chrome.storage.local.remove(stale);
}

// ---------------------------------------------------------------- 与页面通信
async function sendToTab(tabId, msg) {
  try {
    return await chrome.tabs.sendMessage(tabId, msg);
  } catch (e) {
    // 有些页面（刚打开、或 content script 还没注入）需要补注入一次
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
      return await chrome.tabs.sendMessage(tabId, msg);
    } catch (e2) {
      return null;
    }
  }
}

function tell(tabId, msg) { sendToTab(tabId, msg); }

// ---------------------------------------------------------------- 主流程
let running = new Set();

async function runCheck(tab) {
  if (!tab || !tab.id) return;
  if (running.has(tab.id)) return;      // 防连点
  running.add(tab.id);

  const tabId = tab.id;
  const t0 = Date.now();
  try {
    const sel = await sendToTab(tabId, { type: 'yz:getSelection' });
    if (!sel) {
      await sendToTab(tabId, { type: 'yz:error', message: '这个页面无法注入脚本（浏览器内置页面/扩展商店等），换普通网页试试。' });
      return;
    }
    const text = (sel.text || '').trim();
    if (!text) {
      await sendToTab(tabId, { type: 'yz:error', message: '请先用鼠标选中一段文字，再按 Ctrl+Shift+X。', rect: sel.rect });
      return;
    }
    if (text.length > 2000) {
      await sendToTab(tabId, { type: 'yz:error', message: `选中的文字太长了（${text.length} 字），请只选要核查的那几句。`, rect: sel.rect });
      return;
    }

    const cfg = await getConfig();
    const problems = checkConfig(cfg);
    if (problems.length) {
      await sendToTab(tabId, {
        type: 'yz:error', rect: sel.rect,
        message: `还没配置好：${problems.join('；')}。点扩展图标 → 右键 → 选项，填好再试。`,
      });
      return;
    }

    tell(tabId, { type: 'yz:start', rect: sel.rect, text });

    const cached = await readCache(cfg, text);
    if (cached) {
      tell(tabId, {
        type: 'yz:result', rect: sel.rect, text, cached: true, elapsed: 0,
        overall: cached.overall, claims: cached.claims, results: cached.results,
        tokens: cached.tokens, provider: cfg.provider,
      });
      return;
    }

    const out = await checkText(cfg, text, (stage, info) => {
      tell(tabId, { type: 'yz:progress', stage, info });
    });

    if (!out.claims.length) {
      tell(tabId, {
        type: 'yz:result', rect: sel.rect, text, overall: 'none',
        claims: [], results: [], tokens: totalTokens(out.usages),
        provider: cfg.provider, elapsed: (Date.now() - t0) / 1000,
      });
      return;
    }

    const overall = overallVerdict(out.results);
    const tokens = totalTokens(out.usages);
    const elapsed = (Date.now() - t0) / 1000;

    await writeCache(cfg, text, {
      overall, claims: out.claims, results: out.results, tokens,
    });

    tell(tabId, {
      type: 'yz:result', rect: sel.rect, text, overall,
      claims: out.claims, results: out.results,
      tokens, provider: cfg.provider, elapsed,
    });
  } catch (e) {
    tell(tabId, { type: 'yz:error', message: String((e && e.message) || e) });
  } finally {
    running.delete(tabId);
  }
}

// ---------------------------------------------------------------- 触发入口
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'check-selection') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  runCheck(tab);
});

chrome.action.onClicked.addListener((tab) => runCheck(tab));

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'yz-check',
    title: '用「验真」核查选中的文字',
    contexts: ['selection'],
  });
  chrome.runtime.openOptionsPage();
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'yz-check') runCheck(tab);
});

// 设置页点「测试连接」时用
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== 'yz:test') return false;
  (async () => {
    try {
      const cfg = await getConfig();
      const res = await fetch(cfg.baseUrl.replace(/\/$/, '') + '/models', {
        headers: { Authorization: 'Bearer ' + cfg.deepseekKey },
      });
      const ok = res.ok;
      let names = [];
      if (ok) {
        const data = await res.json();
        names = (data.data || []).map((m) => m.id);
      }
      sendResponse({ ok, status: res.status, models: names });
    } catch (e) {
      sendResponse({ ok: false, error: String(e.message || e) });
    }
  })();
  return true;   // 异步响应
});

export { DEFAULTS, VERDICT_LABEL };
