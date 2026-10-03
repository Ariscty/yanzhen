# -*- coding: utf-8 -*-
"""DeepSeek 对话接口。

只用 Python 标准库（urllib），不需要 pip install 任何东西。
"""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def _post(cfg, body, timeout=120):
    url = cfg["DEEPSEEK_BASE_URL"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["DEEPSEEK_API_KEY"],
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat(cfg, system, user, json_mode=True, temperature=0.2,
         max_tokens=2048, retries=2):
    """返回 (文本, usage字典)。失败抛 LLMError。

    ⚠️ 重要：V4.1 是带思考过程的模型，**思考也占用 max_tokens**。
    如果思考太长，正式回答会被挤成空字符串。所以这里检测到空内容时，
    自动把预算翻倍重试，而不是直接把空串丢给 JSON 解析器去崩。
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    budget = max_tokens
    last = None

    for _ in range(retries + 1):
        body = {
            "model": cfg["DEEPSEEK_MODEL"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": budget,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        try:
            data = _post(cfg, body)
            text = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}

            if not text.strip():
                think = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                last = LLMError(
                    "模型返回空内容：max_tokens=%d 被思考过程耗尽（思考用了 %s 个 token）"
                    % (budget, think if think is not None else "未知"))
                budget = min(budget * 2, 16384)     # 下一轮加大预算再试
                continue

            return text, usage

        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            last = LLMError("DeepSeek 返回 HTTP %s：%s" % (e.code, detail))
        except Exception as e:
            last = LLMError("%s: %s" % (type(e).__name__, e))

    raise last


def parse_json(text):
    """模型有时把 JSON 包在 ``` 里，这里做容错解析。"""
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) > 1:
            t = parts[1]
        if t.lower().startswith("json"):
            t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise
