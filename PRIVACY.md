# 隐私政策 · Privacy Policy

**验真 YanZhen — 划词事实核查**
最后更新：2026-10-04

---

## 一句话

**本扩展没有服务器，作者收不到你的任何数据。** 你划中的文字只会发给你自己配置的两家 API
（DeepSeek 和搜索服务），不经过任何第三方中转。

---

## 一、你划中的文字会去哪些地方

当你在网页上选中一段文字并触发核查时，会发生三件事：

| # | 什么数据 | 发到哪里 | 用途 |
|---|---|---|---|
| 1 | **你选中的那段文字** | DeepSeek（`api.deepseek.com`） | 拆分成可核查的断言，并生成检索关键词 |
| 2 | **检索关键词**（由第 1 步从原文生成，可能包含原文片段） | Tavily（`api.tavily.com`）或 博查（`api.bochaai.com`）——**只用你在设置里选的那一家** | 搜索相关证据 |
| 2b | **搜索命中的网页网址**（不含你选中的文字） | Tavily（`api.tavily.com`） | 抓取这些网页的正文，让模型看到原文而不只是摘要。可在设置里关掉 |
| 3 | **搜索到的网页标题、正文（或摘要）、链接** + 断言文字 | DeepSeek（`api.deepseek.com`） | 依据证据作出判定 |

除此之外，**没有任何数据被发送到其他地方**。本扩展没有作者自建的服务器。

## 二、本地保存了什么

全部保存在你自己的浏览器里（`chrome.storage.local`），**不上传**：

| 内容 | 说明 |
|---|---|
| DeepSeek / Tavily / 博查 的 API key | 你自己填的密钥 |
| 设置项 | 模型名、证据条数、缓存天数等 |
| **核查结果缓存** | 默认保留 **7 天**，键是原文的哈希值，内容是核查结果（**含拆分出的断言文字**） |

**关掉缓存**：设置页里把「结果缓存天数」设为 `0`，扩展就不会在本地保留任何核查记录。

## 三、明确不做的事

- ❌ 不收集你的浏览历史
- ❌ **不读取、不上传你访问的网页地址**（代码中没有任何地方获取页面 URL）
- ❌ 没有埋点统计、没有崩溃上报、没有远程日志
- ❌ 不出售、不共享、不分析你的任何数据（因为根本收不到）

## 四、第三方

数据只流向你自己配置的服务，请阅读它们的隐私政策：

- DeepSeek：https://platform.deepseek.com/
- Tavily：https://app.tavily.com
- 博查：https://open.bochaai.com

**注意**：你把 API key 填进本扩展，等于以你自己的账号调用这些服务，费用和数据处理规则都由你与它们之间的协议决定。

## 五、权限说明

| 权限 | 为什么需要 |
|---|---|
| `storage` | 在你电脑本地保存 API key、设置和核查结果缓存 |
| `contextMenus` | 提供右键菜单「用『验真』核查选中的文字」 |
| `activeTab` | 读取你在当前页面选中的文字 |
| `scripting` | 把核查结果的浮动卡片画到当前页面上 |
| `host_permissions`（3 个 API 域名） | 调用你自己配置的模型和搜索服务 |
| 在所有网页上运行（`<all_urls>`） | **因为你可能在任意网页上划词**；扩展只在按下快捷键/点右键时才读取选中文字，不浏览页面内容 |

## 六、免责

本工具是**辅助参考**，不构成事实认定，也不能作为法律、医疗、投资的判断依据。
判定完全取决于检索到的证据和模型的推理，**可能出错**。重要事项请自行核实一手来源。

## 七、联系

问题或建议请提 Issue：https://github.com/Ariscty/yanzhen/issues

---

# Privacy Policy (English)

**YanZhen — select text, check the facts.**
Last updated: 2026-10-04

**In one sentence: there is no backend.** The developer never receives your data.
Selected text is sent only to the two API providers **you** configure.

### What leaves your browser

| # | Data | Sent to | Purpose |
|---|---|---|---|
| 1 | The text you selected | DeepSeek (`api.deepseek.com`) | Split into checkable claims; generate search keywords |
| 2 | The search keywords (generated from the text; may contain fragments of it) | Tavily (`api.tavily.com`) or Bocha (`api.bochaai.com`) — whichever you selected | Retrieve evidence |
| 2b | The **URLs of the pages found** (not the text you selected) | Tavily (`api.tavily.com`) | Fetch those pages' full text so the model sees the source rather than a snippet. Can be turned off in settings |
| 3 | Retrieved titles, page text (or snippets), URLs + the claims | DeepSeek (`api.deepseek.com`) | Produce the verdict |

Nothing is sent anywhere else. The extension has no developer-operated server.

### Stored locally (never uploaded)

API keys, your settings, and a **result cache** (default 7 days) keyed by a hash of the
selected text. Set "cache days" to `0` to store no check history at all.

### Explicitly not done

No browsing history collection. **The extension never reads or transmits the URL of the page
you are on.** No analytics, no telemetry, no crash reporting.

### Third parties

DeepSeek, Tavily and Bocha process your requests under **their own** privacy policies and
your own account with them.

### Contact

https://github.com/Ariscty/yanzhen/issues
