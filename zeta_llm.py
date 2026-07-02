#!/usr/bin/env python3
"""Zeta IDX — LLM client (Claude via 9router, OpenAI-compatible SSE stream)."""
import urllib.request, urllib.error, json, re, os

_CFG = os.environ.get("ZETA_ROOT", "/opt/data") + "/config.yaml"


def _creds():
    cfg = open(_CFG).read()
    # Extract 9router block first, then parse fields within it
    blk = re.search(r'9router:\s*\n((?:[ \t]+.+\n?)*)', cfg)
    if not blk:
        raise ValueError(f"9router block not found in {_CFG}")
    block = blk.group(1)
    m_url = re.search(r'base_url:\s*(\S+)', block)
    m_key = re.search(r'api_key:\s*(\S+)', block)
    if not m_url or not m_key:
        raise ValueError(f"9router base_url/api_key missing in {_CFG}")
    return m_url.group(1).rstrip("/"), m_key.group(1)


def chat(messages, model="cc/claude-sonnet-4-6", max_tokens=1024, timeout=90):
    """Call 9router chat completion. Handles SSE stream, returns full text.
    Note: temperature omitted — deprecated on claude-opus-4-x models."""
    import time
    base, key = _creds()
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            raw = urllib.request.urlopen(req, timeout=timeout).read().decode(errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 3:
                time.sleep(10 * (attempt + 1))  # 10s, 20s, 30s
                continue
            raise
    # SSE: collect delta.content from each `data: {...}` line
    parts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
            delta = obj.get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                parts.append(delta["content"])
            # non-stream fallback
            msg = obj.get("choices", [{}])[0].get("message", {})
            if msg.get("content"):
                parts.append(msg["content"])
        except Exception:
            continue
    return "".join(parts).strip()


def chat_json(messages, **kw):
    """Call chat, extract first balanced JSON object from reply."""
    txt = chat(messages, **kw)
    # find first '{' then walk to find balanced closing '}'
    start = txt.find('{')
    if start == -1:
        raise ValueError("no JSON in reply: " + txt[:200])
    depth = 0
    end = start
    in_str = False
    esc = False
    for i, ch in enumerate(txt[start:], start):
        if esc:
            esc = False; continue
        if ch == '\\' and in_str:
            esc = True; continue
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i; break
    candidate = txt[start:end+1]
    try:
        return json.loads(candidate)
    except Exception as e:
        raise ValueError(f"JSON parse error ({e}): {candidate[:300]}")


if __name__ == "__main__":
    print(chat([{"role": "user", "content": "say OK"}], max_tokens=10))
