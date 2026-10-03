// 验真 · 页面脚本
// 职责：记住用户选中的文字和位置 → 收到后台消息时渲染浮动卡片
//
// 安全注意：选中文字和模型输出都属于「不可信内容」，一律用 textContent 插入，
// 绝不拼 innerHTML —— 否则一个恶意网页就能靠选中的文字往页面里注入脚本。
(() => {
  // ⚠️ 这里不能用 "已加载过就直接 return"。
  // 扩展重载之后，页面里旧的内容脚本会变成"孤儿"（chrome.runtime 已失效），
  // 但它在 window 上留下的标记还在。如果新注入的脚本看到标记就 return，
  // 就永远没人监听消息了 —— 表现就是"按了快捷键毫无反应"。
  // 所以：加事件监听只做一次，但**消息监听永远重新注册**。
  const firstRun = !window.__yanzhenLoaded;
  window.__yanzhenLoaded = true;

  // 上一次留下的卡片（扩展重载后新脚本不认识它了），先清掉，免得叠出两张
  const staleHost = document.getElementById('yanzhen-card-host');
  if (staleHost) staleHost.remove();

  const BADGE = {
    supported: ['🟢', '可信', '#16a34a'],
    refuted: ['🔴', '与事实不符', '#dc2626'],
    mixed: ['🟠', '部分属实', '#ea580c'],
    insufficient: ['🟡', '证据不足', '#d97706'],
    none: ['⚪', '没有可核查的内容', '#6b7280'],
  };
  const STAGE_TEXT = {
    split: '正在拆分断言…',
    search: '正在检索证据…',
    searching: '正在检索：',
    judge: '正在基于证据判定…',
  };

  let lastSel = { text: '', rect: null };
  let card = null;          // { host, root, body, footer }
  let anchorRect = null;

  // ---------------------------------------------------------- 记住选中
  function captureSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const text = sel.toString();
    if (!text.trim()) return;
    let rect = null;
    try {
      const r = sel.getRangeAt(0).getBoundingClientRect();
      if (r && (r.width || r.height)) rect = { top: r.top, left: r.left, bottom: r.bottom, right: r.right };
    } catch (e) { /* 忽略 */ }
    lastSel = { text, rect };
  }
  if (firstRun) {
    document.addEventListener('mouseup', () => setTimeout(captureSelection, 0), true);
    document.addEventListener('keyup', (e) => {
      if (e.shiftKey || e.key === 'Shift') setTimeout(captureSelection, 0);
    }, true);
  }   // ← firstRun 结束：下面的消息监听每次注入都要重新注册

  // ---------------------------------------------------------- 卡片
  const CSS = `
    :host { all: initial; }
    .wrap {
      position: fixed; width: 380px; max-height: 72vh; display: flex; flex-direction: column;
      background: #fff; color: #111827; border: 1px solid #e5e7eb; border-radius: 12px;
      box-shadow: 0 12px 32px rgba(0,0,0,.18); z-index: 2147483647;
      font: 13px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
      overflow: hidden;
    }
    header {
      display: flex; align-items: center; gap: 8px; padding: 8px 12px;
      background: #f9fafb; border-bottom: 1px solid #e5e7eb; cursor: move; user-select: none;
    }
    header .logo { font-weight: 700; font-size: 13px; color: #111827; }
    header .sub { color: #9ca3af; font-size: 11px; }
    header .spacer { flex: 1; }
    header button {
      border: 0; background: transparent; font-size: 18px; line-height: 1; cursor: pointer;
      color: #9ca3af; padding: 0 4px;
    }
    header button:hover { color: #111827; }
    .body { padding: 12px; overflow-y: auto; }
    .overall { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; margin-bottom: 4px; }
    .note { color: #6b7280; font-size: 12px; }
    .claim { margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e5e7eb; }
    .claim:first-of-type { border-top: 0; padding-top: 0; }
    .claim .txt { font-weight: 600; margin-bottom: 4px; }
    .vline { display: flex; align-items: center; gap: 6px; font-size: 12px; margin-bottom: 2px; }
    .vline .conf { color: #6b7280; }
    .reason { color: #374151; margin-bottom: 4px; }
    .tiers { color: #6b7280; font-size: 11px; margin-bottom: 4px; }
    .src { margin: 2px 0 0 0; padding: 0; list-style: none; }
    .src li { margin: 3px 0; font-size: 12px; }
    .src a { color: #2563eb; text-decoration: none; }
    .src a:hover { text-decoration: underline; }
    .tag { display: inline-block; min-width: 15px; text-align: center; background: #f3f4f6;
           border-radius: 3px; color: #6b7280; font-size: 10px; padding: 0 3px; margin-right: 4px; }
    .warn { margin-top: 8px; color: #b45309; background: #fffbeb; border: 1px solid #fde68a;
            border-radius: 6px; padding: 6px 8px; font-size: 12px; }
    .err { color: #b91c1c; }
    footer {
      padding: 6px 12px; border-top: 1px solid #e5e7eb; background: #f9fafb;
      color: #9ca3af; font-size: 11px; display: flex; gap: 10px; flex-wrap: wrap;
    }
    .spin { display: inline-block; width: 12px; height: 12px; border: 2px solid #e5e7eb;
            border-top-color: #6b7280; border-radius: 50%; animation: sp .8s linear infinite; }
    @keyframes sp { to { transform: rotate(360deg); } }
  `;

  function ensureCard() {
    if (card) return card;
    const host = document.createElement('div');
    host.id = 'yanzhen-card-host';       // 留给"扩展重载后清理旧卡片"用
    host.style.all = 'initial';
    const root = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = CSS;
    const wrap = document.createElement('div');
    wrap.className = 'wrap';

    const header = document.createElement('header');
    const logo = document.createElement('span');
    logo.className = 'logo';
    logo.textContent = '验真';
    const sub = document.createElement('span');
    sub.className = 'sub';
    sub.textContent = '划词事实核查';
    const spacer = document.createElement('span');
    spacer.className = 'spacer';
    const close = document.createElement('button');
    close.textContent = '×';
    close.title = '关闭 (Esc)';
    close.addEventListener('click', removeCard);
    header.append(logo, sub, spacer, close);

    const body = document.createElement('div');
    body.className = 'body';
    const foot = document.createElement('footer');

    wrap.append(header, body, foot);
    root.append(style, wrap);
    document.documentElement.appendChild(host);
    card = { host, root, wrap, body, foot };

    // 拖动
    let drag = null;
    header.addEventListener('mousedown', (e) => {
      if (e.target === close) return;
      const r = wrap.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!drag) return;
      wrap.style.left = Math.max(4, Math.min(window.innerWidth - 60, e.clientX - drag.dx)) + 'px';
      wrap.style.top = Math.max(4, Math.min(window.innerHeight - 40, e.clientY - drag.dy)) + 'px';
    });
    window.addEventListener('mouseup', () => { drag = null; });
    return card;
  }

  function positionCard(rect) {
    const { wrap } = ensureCard();
    const w = 380, margin = 10;
    let left, top;
    if (rect) {
      left = Math.min(Math.max(margin, rect.left), window.innerWidth - w - margin);
      top = rect.bottom + 8;
      if (top > window.innerHeight - 200) top = Math.max(margin, rect.top - 260);
    } else {
      left = window.innerWidth - w - 20;
      top = 20;
    }
    wrap.style.left = left + 'px';
    wrap.style.top = top + 'px';
  }

  function removeCard() {
    if (card) { card.host.remove(); card = null; }
    document.removeEventListener('keydown', onKey, true);
  }
  function onKey(e) { if (e.key === 'Escape') removeCard(); }

  function clearBody() {
    const { body, foot } = ensureCard();
    body.textContent = '';
    foot.textContent = '';
  }

  function link(url, label) {
    const a = document.createElement('a');
    if (/^https?:\/\//i.test(url)) { a.href = url; a.target = '_blank'; a.rel = 'noreferrer noopener'; }
    a.textContent = label;
    return a;
  }

  // ---------------------------------------------------------- 渲染
  function renderProgress(stage, info) {
    ensureCard();
    clearBody();
    const { body } = card;
    const line = document.createElement('div');
    line.className = 'vline';
    const sp = document.createElement('span');
    sp.className = 'spin';
    const t = document.createElement('span');
    t.textContent = (STAGE_TEXT[stage] || '处理中…') + (stage === 'searching' ? info : '');
    line.append(sp, t);
    body.appendChild(line);
    const tip = document.createElement('div');
    tip.className = 'note';
    tip.textContent = '通常需要 10~20 秒';
    body.appendChild(tip);
    document.addEventListener('keydown', onKey, true);
  }

  function renderError(message, rect) {
    ensureCard();
    positionCard(rect || anchorRect);
    clearBody();
    const { body, foot } = card;
    const b = document.createElement('div');
    b.className = 'overall err';
    b.textContent = '出错了';
    const m = document.createElement('div');
    m.className = 'reason';
    m.textContent = message;
    body.append(b, m);
    foot.textContent = '验真 · 辅助参考，不构成事实认定';
    document.addEventListener('keydown', onKey, true);
  }

  function renderResult(payload) {
    ensureCard();
    positionCard(payload.rect || anchorRect);
    clearBody();
    const { body, foot } = card;

    const [icon, label, color] = BADGE[payload.overall] || BADGE.insufficient;
    const overall = document.createElement('div');
    overall.className = 'overall';
    overall.style.color = color;
    overall.textContent = `${icon} ${label}`;
    if (payload.results.length > 1) {
      const hits = payload.results.filter((r) => r.verdict === 'refuted').length;
      if (hits) {
        const extra = document.createElement('span');
        extra.className = 'note';
        extra.textContent = `（${payload.results.length} 条断言中 ${hits} 条与事实不符）`;
        overall.appendChild(extra);
      }
    }
    body.appendChild(overall);

    if (!payload.results.length) {
      const n = document.createElement('div');
      n.className = 'note';
      n.textContent = '这段话里没有找到可以核查的事实性断言（可能全是观点或情绪表达）。';
      body.appendChild(n);
    }

    payload.results.forEach((r, i) => {
      const block = document.createElement('div');
      block.className = 'claim';

      const txt = document.createElement('div');
      txt.className = 'txt';
      txt.textContent = `${i + 1}. ${r.claim || (payload.claims[i] && payload.claims[i].claim) || ''}`;
      block.appendChild(txt);

      const [ic, lb, cl] = BADGE[r.verdict] || BADGE.insufficient;
      const vl = document.createElement('div');
      vl.className = 'vline';
      vl.style.color = cl;
      const strong = document.createElement('strong');
      strong.textContent = `${ic} ${lb}`;
      const conf = document.createElement('span');
      conf.className = 'conf';
      conf.textContent = `置信度 ${Math.round((r.confidence || 0) * 100)}%`;
      vl.append(strong, conf);
      block.appendChild(vl);

      const rn = document.createElement('div');
      rn.className = 'reason';
      rn.textContent = r.reason || '（模型没给理由）';
      block.appendChild(rn);

      // 引用来源的等级分布 —— 一眼看出这个判定是拿什么撑起来的。
      // 等级由 core.js 算好后随结果一起发过来，这里只负责显示（不重复实现分级规则）。
      const cited = r.sources || [];
      if (cited.length) {
        const dist = document.createElement('div');
        dist.className = 'tiers';
        dist.textContent = `引用来源等级：${r.tierSummary || '—'}`
          + (r.tierStrong ? '' : '  ← 没有 A/B 级来源');
        block.appendChild(dist);
      }

      const ul = document.createElement('ul');
      ul.className = 'src';
      for (const s of cited.slice(0, 5)) {
        const li = document.createElement('li');
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = s.tier || '?';
        li.appendChild(tag);
        li.appendChild(link(s.url, (s.title || s.url || '').slice(0, 60)));
        ul.appendChild(li);
      }
      if (ul.children.length) block.appendChild(ul);
      else {
        const none = document.createElement('div');
        none.className = 'tiers';
        none.textContent = '（模型未引用任何来源，请谨慎采信）';
        block.appendChild(none);
      }

      if (r.droppedSources && r.droppedSources.length) {
        const w = document.createElement('div');
        w.className = 'warn';
        w.textContent = `⚠️ 已剔除 ${r.droppedSources.length} 条模型编造的来源（不在检索结果里）`;
        block.appendChild(w);
      }
      body.appendChild(block);
    });

    if (payload.cached) {
      const c = document.createElement('div');
      c.className = 'note';
      c.textContent = '（这段文字之前核查过，直接复用上次结论，没有产生费用）';
      body.appendChild(c);
    }
    if (payload.provider === 'mock') {
      const w = document.createElement('div');
      w.className = 'warn';
      w.textContent = '⚠️ 当前用的是模拟搜索，证据是假的，结论不可当真。';
      body.appendChild(w);
    }

    const parts = [];
    parts.push(payload.provider === 'mock' ? '模拟搜索' : `搜索来源：${payload.provider}`);
    if (typeof payload.elapsed === 'number' && payload.elapsed > 0) parts.push(`耗时 ${payload.elapsed.toFixed(1)} 秒`);
    if (payload.tokens) parts.push(`${payload.tokens} token`);
    foot.textContent = parts.join(' · ') + ' · 辅助参考，不构成事实认定';
    document.addEventListener('keydown', onKey, true);
  }

  // 来源分级规则不在这里实现 —— core.js 算好后随结果一起发过来。
  // （content script 不能用 ES 模块 import，抄一遍迟早两边不一致。）

  // ---------------------------------------------------------- 消息
  // 幂等注册：同一个上下文被重复注入时，先摘掉上一次的监听，免得响应两次
  if (window.__yanzhenOnMessage) {
    try { chrome.runtime.onMessage.removeListener(window.__yanzhenOnMessage); }
    catch (e) { /* 忽略 */ }
  }

  window.__yanzhenOnMessage = (msg, sender, sendResponse) => {
    if (!msg || !msg.type) return false;
    switch (msg.type) {
      case 'yz:getSelection': {
        captureSelection();
        sendResponse({ text: lastSel.text, rect: lastSel.rect });
        return false;
      }
      case 'yz:start':
        anchorRect = msg.rect || null;
        renderProgress('split', '');
        return false;
      case 'yz:progress':
        renderProgress(msg.stage, msg.info);
        return false;
      case 'yz:result':
        renderResult(msg);
        return false;
      case 'yz:error':
        renderError(msg.message, msg.rect);
        return false;
      default:
        return false;
    }
  };

  chrome.runtime.onMessage.addListener(window.__yanzhenOnMessage);
})();
