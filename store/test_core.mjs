/**
 * 验真 · 内核自测（Node 版，推荐）
 * ================================
 * 直接 import 扩展内核 core.js 跑断言 —— 不需要浏览器，跨平台。
 *
 * 为什么比 store/test_core.py 好：
 *   · test_core.py 靠 Edge 无头模式执行（本机没有 Node 时的备选方案），
 *     但它写死了 Windows 下 Edge 的安装路径，在 mac/linux 上用不了；
 *   · Node 到处都是，而且能直接 import ESM 模块，更快也不需要放宽沙箱。
 *
 * 覆盖的都是最容易出错、又不需要联网、不花 API 钱的纯逻辑：
 *   · tierOf          来源分级（A/B/C/D/当事方/未分级）
 *   · factCheckQuery  辟谣检索关键词生成（v8 新增）
 *   · verifySources   引用校验硬闸门（模型编的网址必须被剔除）
 *   · overallVerdict  总判定优先级（refuted 必须压过 mixed —— 回归事故的核心规则）
 *   · 四个 JS 文件的语法
 *
 * 用法：
 *   node store/test_core.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const EXT = join(ROOT, 'extension');
const tmp = mkdtempSync(join(tmpdir(), 'yz-'));

let pass = 0, fail = 0;
const ok = (name, got, want, extra = '') => {
  const good = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${good ? 'OK  ' : 'FAIL'} ${name.padEnd(38)} ${JSON.stringify(got)}${extra}`);
  good ? pass++ : fail++;
};

// ─────────────────────────── 语法检查 ───────────────────────────
// 用进程内的 new Function() 解析，**不 spawn 子进程** ——
// spawnSync 在受限环境里会因命名管道被禁而报 EPERM，
// 那看起来像"语法错误"，其实是环境问题，很误导人。
// 代价：import/export 行要先去掉（new Function 不认识它们）。
console.log('【JS 语法】');
function syntaxOk(file) {
  // 注意：import 是整条语句（整行删掉）；
  //       export 只是**前缀**（只删关键字，保留后面的声明）——
  //       把 `export const TIER = {` 整行删掉会留下悬空的对象体，
  //       报出假的"Unexpected token"。
  let code = readFileSync(join(EXT, file), 'utf-8')
    .replace(/^\s*import\s+.*$/gm, '')
    .replace(/^(\s*)export\s+/gm, '$1');
  try {
    new Function(code);
    return null;
  } catch (e) {
    return e.message;
  }
}
for (const f of ['core.js', 'background.js', 'content.js', 'options.js']) {
  const err = syntaxOk(f);
  ok(f, err ? '语法错误: ' + err : '语法 OK', '语法 OK');
}

// ─────────────────────────── 功能测试 ───────────────────────────
const core = await import(pathToFileURL(join(EXT, 'core.js')).href);

console.log('\n【PROMPT_VERSION】');
// ⚠️ 改提示词或改流程后这里要跟着改 —— 它同时在提醒你：版本号必须 +1，
//    否则结果缓存不会失效，评测会返回旧结论。
ok('版本号（Python 版 check.py 必须一致）', core.PROMPT_VERSION, '9');

console.log('\n【来源分级 tierOf】');
ok('中国政府网', core.tierOf('https://www.gov.cn/a.htm')[0], 'A 官方一手');
ok('WHO', core.tierOf('https://www.who.int/x')[0], 'A 官方一手');
ok('英国政府', core.tierOf('https://www.gov.uk/x')[0], 'A 官方一手');
ok('中国疾控中心', core.tierOf('https://www.chinacdc.cn/x')[0], 'A 官方一手');
ok('新华网', core.tierOf('https://www.xinhuanet.com/x.htm')[0], 'B 权威媒体');
ok('澎湃新闻', core.tierOf('https://www.thepaper.cn/x')[0], 'B 权威媒体');
ok('OpenAI 官网（当事方）', core.tierOf('https://openai.com/x')[0], 'A 当事方官网');
ok('微博', core.tierOf('https://weibo.com/1')[0], 'D 自媒体百科');
ok('知乎', core.tierOf('https://www.zhihu.com/q/1')[0], 'D 自媒体百科');
ok('认不出的域名', core.tierOf('https://random.example/1')[0], '未分级');
ok('空 URL', core.tierOf('')[0], '未分级');

// factCheckQuery 没导出：复制一份内核、末尾补上导出，再 import 来单测
{
  const patched = join(tmp, 'core_x.mjs');
  writeFileSync(patched,
    readFileSync(join(EXT, 'core.js'), 'utf-8') + '\nexport { factCheckQuery };\n');
  const m = await import(pathToFileURL(patched).href);
  console.log('\n【辟谣关键词 factCheckQuery】(v8 新增)');
  ok('中文断言', m.factCheckQuery({ query: '隔夜水 致癌 亚硝酸盐' }), '隔夜水 致癌 亚硝酸盐 辟谣 真相');
  ok('英文断言', m.factCheckQuery({ query: 'overnight water cancer' }), 'overnight water cancer fact check');
  ok('中英混排按中文处理', m.factCheckQuery({ claim: 'NMN 抗衰老' }), 'NMN 抗衰老 辟谣 真相');
  ok('只有 claim 没有 query', m.factCheckQuery({ claim: '微波炉致癌' }), '微波炉致癌 辟谣 真相');
  ok('空输入', m.factCheckQuery({}), '');
}

console.log('\n【引用校验硬闸门 verifySources】');
{
  const results = [{ sources: [
    { url: 'https://www.gov.cn/a.htm', title: '真来源' },
    { url: 'https://fake-hallucinated.com/x', title: '模型编的' },
    { url: '  https://www.xinhuanet.com/b.htm  ', title: '带空格的真来源' },
    { url: '', title: '空网址' },
  ] }];
  const claims = [{ evidence: [
    { url: 'https://www.gov.cn/a.htm' },
    { url: 'https://www.xinhuanet.com/b.htm' },
  ] }];
  const out = core.verifySources(results, claims);
  ok('保留（含去空格）', out[0].sources.map((s) => s.title), ['真来源', '带空格的真来源']);
  ok('剔除（编造 + 空）',
     out[0].droppedSources.map((s) => s.title).sort(), ['模型编的', '空网址'].sort());
}

console.log('\n【总判定优先级 overallVerdict】');
ok('refuted 压过 mixed（回归事故核心）',
   core.overallVerdict([{ verdict: 'refuted' }, { verdict: 'mixed' }]), 'refuted');
ok('refuted 压过 supported',
   core.overallVerdict([{ verdict: 'supported' }, { verdict: 'refuted' }]), 'refuted');
ok('mixed 压过 supported',
   core.overallVerdict([{ verdict: 'mixed' }, { verdict: 'supported' }]), 'mixed');
ok('全 supported 才可信',
   core.overallVerdict([{ verdict: 'supported' }, { verdict: 'supported' }]), 'supported');
ok('有 insufficient 且无否证',
   core.overallVerdict([{ verdict: 'supported' }, { verdict: 'insufficient' }]), 'insufficient');
ok('空数组', core.overallVerdict([]), 'insufficient');

console.log('\n【等级汇总】');
ok('tierSummary 显示归并',
   core.tierSummary([core.TIER.A, core.TIER.P, core.TIER.B, core.TIER.B, core.TIER.D, core.TIER.U]),
   'A×2 B×2 D×1 ?×1');
ok('hasStrongTiers(A,B)', core.hasStrongTiers([core.TIER.A, core.TIER.B]), true);
ok('hasStrongTiers(C,D)', core.hasStrongTiers([core.TIER.C, core.TIER.D]), false);

rmSync(tmp, { recursive: true, force: true });

console.log('\n' + '='.repeat(56));
console.log(`通过 ${pass} / 失败 ${fail}`);
console.log('='.repeat(56));
if (fail) {
  console.log('\n⚠️ 有失败项 —— 别急着提交，先看上面的差异。');
  process.exit(1);
}
console.log('\n✅ 内核纯逻辑全部通过。');
