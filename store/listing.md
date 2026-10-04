# 商店上架文案 · Store Listing Copy

> 直接复制粘贴到 Edge 加载项 / Chrome Web Store 的后台表单。
> 带 ⚠️ 的地方是审核最容易卡住的，别改。

---

## 一、基本信息

| 字段 | 填什么 |
|---|---|
| 名称（中文，主语言） | 验真 YanZhen — 划词事实核查 |
| 名称（英文） | YanZhen — Fact-check Selected Text |
| 分类 Category | Productivity（生产力工具） |
| 语言 | 中文（简体）为主，附英文 |
| 官方网站 | https://github.com/Ariscty/yanzhen |
| 支持邮箱 | （填你自己的邮箱，**必填，审核会用它联系你**） |
| 隐私政策 URL | https://github.com/Ariscty/yanzhen/blob/main/PRIVACY.md |

---

## 二、简短描述（≤132 字符，Chrome 硬限制）

**中文：**

```
选中网页上的一段文字，按 Ctrl+Shift+X，它告诉你这段话能不能信、凭什么。结论 + 证据来源，查不到就直说。
```

**English:**

```
Select text on any page, press Ctrl+Shift+X, and get a verdict with sources. If the evidence isn't there, it says so.
```

---

## 三、详细描述

**中文：**

```
搜索引擎给你一堆链接，让你自己判断。验真给你一句结论、拆开的每条断言、以及背后的来源。

【怎么用】
1. 在任意网页上选中一段文字
2. 按 Ctrl+Shift+X（也可以右键菜单，或点工具栏图标）
3. 弹出卡片：结论 + 每条断言的判定 + 可点击的证据来源

【三种结论】
🟢 可信 / 🟡 证据不足 / 🟠 部分属实 / 🔴 与事实不符
还会给出置信度和引用来源的等级，你能自己看它是凭什么下的结论。

【它和普通 AI 问答有什么不一样】
大模型自己不知道真假，只会编。所以本工具不让模型凭记忆下结论：

· 先把一段话拆成若干条可核查的断言，逐条判
· 每条断言中文搜一遍、英文搜一遍；涉及近期事件的自动搜新闻
· 检索结果按来源分级：A 官方一手 / B 权威媒体 / C 专业机构 / D 自媒体，只有 A、B 级来源才能支撑「可信 / 与事实不符」的判定
· 模型给出的每个网址都会和检索结果逐一比对，编造的引用会被剔除并在界面上报警
· 查不到就说查不到 —— 这是本工具的核心态度

【需要你自己准备两个 API key】
为了不经过任何中间服务器，本扩展由你自己填写模型和搜索服务的密钥：
· DeepSeek（模型）— platform.deepseek.com，按 token 计费，一次核查约几分钱
· Tavily（搜索）— app.tavily.com，每月 1000 次免费，不用信用卡
密钥只存在你本机的浏览器里，不会上传到任何地方。

【已知限制（说清楚，不藏）】
· 只能在浏览器里划词，管不到微信、Word、PDF 阅读器
· 同一段文字首次查询（换机器或缓存过期后）可能给出不同结论；缓存期内结果一致
· 尚无科学定论的话题（如阿斯巴甜、NMN），它倾向于给出确定答案，这是当前最弱的一环
· 在 edge:// / chrome:// 等浏览器内置页面上无法使用

【开源】
MIT 协议，代码全部公开：https://github.com/Ariscty/yanzhen
喜欢这个思路可以自己拿去改。

【免责】
本工具是辅助参考，不构成事实认定，也不能作为法律、医疗、投资的判断依据。重要事项请自行核实一手来源。
```

**English:**

```
Search engines hand you a pile of links and leave the judging to you. YanZhen gives you a
verdict, the individual claims behind it, and the sources — or tells you the evidence isn't
there.

HOW TO USE
1. Select text on any web page
2. Press Ctrl+Shift+X (or right-click, or click the toolbar icon)
3. A card appears: verdict + per-claim judgement + clickable sources

VERDICTS
Trustworthy / Insufficient evidence / Partly true / Contradicted — each with a confidence
level and the source tier it rests on.

WHY IT ISN'T JUST ANOTHER AI CHAT
Language models don't know what's true — they make things up. So this tool never lets the
model answer from memory:
- The text is split into individual checkable claims, judged one by one
- Every claim is searched in Chinese AND English; recent-event claims also trigger a news search
- Sources are tiered (official / major media / professional bodies / self-media). Only the
  first two tiers can support a "trustworthy" or "contradicted" verdict
- Every URL the model cites is checked against the actual search results. Fabricated citations
  are stripped out and flagged in the UI
- If the evidence isn't there, it says so. That's the whole point.

YOU BRING YOUR OWN API KEYS
To avoid running any intermediary server, you supply your own keys:
- DeepSeek (model) — platform.deepseek.com, pay per token, roughly a cent or two per check
- Tavily (search) — app.tavily.com, 1,000 free searches per month, no credit card
Keys are stored only in your own browser and are never uploaded anywhere.

KNOWN LIMITATIONS (stated plainly)
- Works only on text selected in the browser — not in WeChat, Word or PDF readers
- The first check of a given text (on a new machine, or after the cache expires) may differ
  from a later one; within the cache window results are identical
- On topics science hasn't settled (aspartame, NMN), it tends to give a definite answer —
  this is the weakest part of the current version
- Doesn't work on browser-internal pages (edge://, chrome://)

OPEN SOURCE
MIT licensed: https://github.com/Ariscty/yanzhen

DISCLAIMER
A reference aid, not a determination of fact, and not a basis for legal, medical or
investment decisions. Verify primary sources yourself.
```

---

## 四、⚠️ 权限说明（审核必看，逐条贴进表单）

**中文：**

```
storage —— 在你本机浏览器里保存 API 密钥、偏好设置和核查结果缓存。不上传任何数据。

contextMenus —— 提供右键菜单项「用『验真』核查选中的文字」，这是三种触发方式之一。

activeTab —— 读取你在当前页面上选中的那段文字。仅在你主动触发核查时读取。

scripting —— 把核查结果的浮动卡片绘制到当前页面上（即你看结果的那个卡片）。

host_permissions（api.deepseek.com / api.tavily.com / api.bochaai.com）——
  这三个域名是你自己填写的模型与搜索服务的 API。扩展的全部联网行为都止于此，
  没有开发者服务器参与。

在所有网页上运行（<all_urls>）——
  因为用户可能在任意网页上遇到需要核查的文字，扩展必须能在那时响应快捷键和右键菜单。
  扩展不会浏览或读取页面内容：只有当你按下 Ctrl+Shift+X 或点击右键菜单时，
  它才读取你当次选中的文字。扩展代码中不存在任何获取页面 URL 或页面全文的逻辑。
```

**English:**

```
storage — Stores your API keys, preferences and a result cache in your local browser only.

contextMenus — Adds the right-click item "Check selected text with YanZhen".

activeTab — Reads the text you selected on the current page, and only when you explicitly
  trigger a check.

scripting — Renders the result card onto the current page.

host_permissions (api.deepseek.com, api.tavily.com, api.bochaai.com) — These are the API
  endpoints you configure yourself. All network activity ends here; there is no developer
  server.

Runs on all websites (<all_urls>) — Users may encounter text worth checking on any page, so
  the extension must be able to respond to the shortcut and context menu there. It does not
  scan or read page content: selected text is read only at the moment you press Ctrl+Shift+X
  or use the context menu. No code in the extension reads the page URL or the full page.
```

---

## 五、⚠️ 隐私实践问卷 / Data usage（Chrome 必答）

Chrome 提交时会问"你收集哪些用户数据"，照这样选：

| 问题 | 选 |
|---|---|
| 是否收集个人身份信息、健康、财务、认证信息、个人通信、位置、网页历史、用户活动？ | **全部不勾** |
| 是否将数据传输给第三方？ | 勾选 ✅（并说明：仅传给你自己配置的 DeepSeek / Tavily API） |
| 是否用于广告、是否出售数据？ | **否** |
| 是否使用远程代码？ | **否** |
| 数据是否加密传输？ | 是（全部走 HTTPS） |

**额外说明栏可以填这句：**

```
本扩展不向开发者回传任何数据。用户选中的文字仅发送到用户自行配置的第三方 API
（DeepSeek 用于模型判定、Tavily 或博查用于检索），用于完成用户主动发起的核查请求。
所有数据均通过 HTTPS 传输，密钥仅保存在用户本机浏览器中。
```

---

## 六、更新说明 / What's new

```
0.3.0
- 新增应用图标
- 补齐商店上架所需的隐私政策与权限说明
- 功能与 0.2.0 一致：划词核查、中英双语检索、新闻模式、来源分级、引用校验
```

---

## 七、截图要求

| 用途 | 尺寸 | 数量 |
|---|---|---|
| 商店截图（必需） | **1280 × 800**（Edge / Chrome 均接受） | 至少 1 张，建议 3 张 |

需要你自己截（我截不了，因为需要你的浏览器在跑扩展）：

1. **主截图**：打开一个含养生谣言的网页 → 选中一句话 → `Ctrl+Shift+X` → **截取卡片弹出的瞬间**（含被选中的文字和卡片）
2. 第二张：设置页（展示"填自己的 key"）
3. 第三张：卡片里点开证据来源的样子

> 截图里**不要出现真实 API key**。设置页截图前先把 key 输入框清空。
