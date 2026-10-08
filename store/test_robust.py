# -*- coding: utf-8 -*-
"""验真 · 健壮性与缓存回归测试（**不联网、不花钱**）

用法：
    python store/test_robust.py

验证三件事，全部靠打桩实现，不调用任何真实 API：

  ① `_repair_json` 的边界 —— 能修 markdown 围栏和前后废话，
     **修不了被真正截断的 JSON**（这是三级兜底的真实边界）

  ② 拆断言缓存 —— 命中时不再调用模型；文本归一化后键稳定；
     `MAX_CLAIMS` 变化时键要变

  ③ **模型吐坏 JSON 时不再让整条核查崩掉** ——
     把 `llm.chat` 打桩成永远返回 "这不是 JSON"，确认 judge() 降级成
     逐条 `insufficient`、token 照常记账、且**不抛异常**。

第 ③ 条对应一个真实事故：评测里 r02 报 `JSONDecodeError`，整条样本直接失败、
白花掉前面所有的检索和模型调用。**查不到就直说，不猜 —— 吐了坏 JSON 也一样。**
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check   # noqa: E402
import llm     # noqa: E402

ok_n = fail_n = 0


def ok(name, cond, extra=''):
    global ok_n, fail_n
    print('  %s %s %s' % ('OK  ' if cond else 'FAIL', name, extra))
    if cond:
        ok_n += 1
    else:
        fail_n += 1


print('【① _repair_json】')
# 能修的：markdown 围栏、前后有废话
# 修不了的：真正被截断的 JSON（末尾少括号）—— 这是三级兜底的真实边界，
#           遇到它就会抛 JudgeParseError，由 judge() 降级成"无法判定"
cases = [
    ('```json\n{"a":1}\n```', True),
    ('好的，结果是：{"a":1} 以上。', True),
    ('{"a":1', False),           # 截断 —— 修不了，如实标注
    ('完全不是 JSON', False),
]
for raw, should_work in cases:
    try:
        out = check._repair_json(raw)
        llm.parse_json(out)
        got = True
    except Exception:
        got = False
    ok('修复 %r -> 可解析=%s' % (raw[:22], got), got is should_work,
       '' if got is should_work else '(期望 %s)' % should_work)

print('\n【② 拆断言缓存】')
check.clear_claim_cache()
cfg = {'MAX_CLAIMS': '3', 'CACHE_DAYS': '7', 'DEEPSEEK_MODEL': 'deepseek-flash'}
text = '隔夜水会致癌，因为反复烧开会产生大量亚硝酸盐'

k1 = check._claim_key(cfg, text)
ok('同一文本键稳定', k1 == check._claim_key(cfg, text))
# 归一化会丢掉标点和空白，所以「加个感叹号」应当**命中同一条缓存** —— 这是故意的：
# 免得上一次查和这一次查因为多了个标点就绕开缓存、重新花钱。
ok('末尾加标点 -> 键不变（归一化故意如此）',
   k1 == check._claim_key(cfg, text + '！'))
ok('换了字 -> 键不同', k1 != check._claim_key(cfg, text.replace('隔夜水', '千滚水')))
ok('换 MAX_CLAIMS -> 键不同',
   k1 != check._claim_key(dict(cfg, MAX_CLAIMS='2'), text))

# 打桩：一旦真的调用模型就报错，用来证明命中缓存时根本没调模型
real_chat = llm.chat
llm.chat = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('不该调用模型！'))
try:
    check.extract_claims(cfg, text)   # 缓存空 → 应该炸
    ok('缓存空时会调用模型', False, '(竟然没炸，说明打桩没生效)')
except RuntimeError:
    ok('缓存空时会调用模型', True)

# 手动塞一条缓存，再调用应该直接返回、不碰模型
check._load_claim_cache()[k1] = {
    't': time.time(),
    'claims': [{'claim': '隔夜水会致癌', 'query': '隔夜水 致癌',
                'query_en': 'overnight water cancer', 'time_sensitive': False}],
}
check._save_claim_cache()
try:
    got_claims, u = check.extract_claims(cfg, text)
    ok('命中缓存不再调用模型', True, '-> %s' % got_claims[0]['claim'])
    ok('命中缓存 usage 为空', u == {})
except Exception as e:
    ok('命中缓存不再调用模型', False, str(e))
llm.chat = real_chat
check.clear_claim_cache()

print('\n【③ 坏 JSON 不再让整条核查崩掉】')
llm.chat = lambda *a, **kw: ('这不是 JSON，模型跑歪了', {'total_tokens': 10})
claims = [{'claim': '断言一'}, {'claim': '断言二'}]
try:
    results, usage = check.judge({'JUDGE_VOTES': '1'}, claims)
    ok('judge 没有抛异常', True)
    ok('每条断言都降级成 insufficient',
       all(r.get('verdict') == 'insufficient' for r in results), '-> %s' % [r['verdict'] for r in results])
    ok('条数与断言数一致', len(results) == 2)
    ok('reason 里说清了原因', '无法解析' in (results[0].get('reason') or ''))
    ok('总判定退化成 insufficient', check.overall_verdict(results) == 'insufficient')
    ok('token 仍然记账', usage.get('total_tokens', 0) > 0, '-> %s' % usage)
except Exception as e:
    ok('judge 没有抛异常', False, '%s: %s' % (type(e).__name__, e))
llm.chat = real_chat

print('\n【④ 拆断言这一步吐坏 JSON，也不许把整条核查炸掉】')
# 为什么要单独测这一步：
#   原来只有「判定」有三级兜底，拆断言直接 llm.parse_json(raw)。
#   评测里 r04 就死在这里 —— 模型第一条断言吐了被截断的 JSON，
#   整条样本直接报错、白花掉前面所有的钱。同一类风险不该只在一半的代码里防。
check.clear_claim_cache()
cfg4 = {'MAX_CLAIMS': '3', 'CACHE_DAYS': '0', 'DEEPSEEK_MODEL': 'deepseek-flash'}
llm.chat = lambda *a, **kw: ('{"claims":[{"claim":"被截断的', {'total_tokens': 7})
try:
    claims4, results4, usages4 = check.run(cfg4, '随便一段待核查的文字')
    ok('run 没有抛异常', True)
    ok('降级成一条 insufficient',
       len(results4) == 1 and results4[0].get('verdict') == 'insufficient',
       '-> %s' % [r.get('verdict') for r in results4])
    ok('reason 点名是拆断言那一步', '拆断言' in (results4[0].get('reason') or ''))
    ok('总判定退化成 insufficient', check.overall_verdict(results4) == 'insufficient')
    tok4 = check.summarize_usage(usages4)['total_tokens']
    ok('token 仍然记账', tok4 > 0, '-> %d' % tok4)
except Exception as e:
    ok('run 没有抛异常', False, '%s: %s' % (type(e).__name__, e))
llm.chat = real_chat
check.clear_claim_cache()

print('\n【⑤ 拆断言缓存不许被下游改写污染】')
# 事故记录：gather_evidence 就地往 claim 上挂 evidence，而 extract_claims
# 曾经把**同一个对象**存进缓存 → 下一次任意样本触发落盘时，整份缓存
# 连证据一起写进磁盘。实测 19 条样本跑完，cache_claims.json 从 281 字节
# 涨到 496KB，里面塞满整页网页正文。
check.clear_claim_cache()
cfg5 = {'MAX_CLAIMS': '3', 'CACHE_DAYS': '7', 'DEEPSEEK_MODEL': 'deepseek-flash'}
llm.chat = lambda *a, **kw: (
    '{"claims":[{"claim":"气泡水","query":"气泡水",'
    '"query_en":"sparkling water","time_sensitive":false}]}',
    {'total_tokens': 5})
try:
    c5, _ = check.extract_claims(cfg5, '气泡水会腐蚀骨头')
    c5[0]['evidence'] = [{'url': 'https://example.com/x', 'content': '污染用的正文'}]
    # 再触发一次落盘（新文本 -> 新键 -> _save_claim_cache）
    check.extract_claims(cfg5, '另一段完全不同的文字')
    raw5 = check.CLAIM_CACHE_FILE.read_text(encoding='utf-8')
    same_key = check._claim_key(cfg5, '气泡水会腐蚀骨头')
    cached5 = check._load_claim_cache().get(same_key, {}).get('claims', [{}])[0]
    ok('内存缓存里没有 evidence 字段', 'evidence' not in cached5,
       '(泄漏了)' if 'evidence' in cached5 else '')
    ok('磁盘缓存里也没有那段污染正文', '污染用的正文' not in raw5)
except Exception as e:
    ok('缓存隔离测试', False, '%s: %s' % (type(e).__name__, e))
llm.chat = real_chat
check.clear_claim_cache()

print('\n' + '=' * 56)
print('通过 %d / 失败 %d' % (ok_n, fail_n))
print('=' * 56)
sys.exit(1 if fail_n else 0)
