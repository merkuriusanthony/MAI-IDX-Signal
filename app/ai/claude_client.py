"""Async Claude client (Anthropic-compatible Messages API).

Falls back to a deterministic template if the API call fails so the pipeline
never blocks on AI availability.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _parse_json_loose(text: str) -> Dict:
    """Parse JSON from a model response that may wrap it in prose/fences.

    Strategy: strip markdown fences, try strict parse, then fall back to
    extracting the outermost {...} object. Raises ValueError if nothing
    parseable is found.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
        t = t.strip()
    # Try strict parse first.
    try:
        return json.loads(t)
    except Exception:
        pass
    # Model wrapped JSON in prose or appended trailing text ("Extra data").
    # Use raw_decode from the first '{' so we stop at the first complete object.
    start = t.find("{")
    if start != -1:
        decoder = json.JSONDecoder()
        try:
            obj, _end = decoder.raw_decode(t[start:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    raise ValueError("no JSON object found in model response")


def _fallback(prompt: str) -> Dict:
    """Deterministic template used when Claude is unavailable."""
    return {
        "summary": "Analisa otomatis berdasarkan indikator teknikal (mode fallback).",
        "key_reasons": ["Skor teknikal dihitung dari indikator deterministik."],
        "risks": ["AI reasoning tidak tersedia, gunakan dengan kehati-hatian."],
        "invalidation_note": "Sinyal batal bila menembus level stop loss.",
        "retail_message": "Selalu gunakan manajemen risiko. Bukan ajakan beli/jual.",
        "_fallback": True,
    }


def _extract_text(data: Dict) -> str:
    """Pull text content out of an Anthropic Messages API response."""
    parts = data.get("content", [])
    chunks = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            chunks.append(p.get("text", ""))
    return "".join(chunks).strip()


def _decode_response(resp: httpx.Response) -> Dict:
    """Decode an Anthropic Messages response, tolerating SSE event-stream.

    Some gateways (9Router) return text/event-stream even when streaming was
    not requested, which makes resp.json() raise "Extra data". Detect that and
    reassemble the message from content_block_delta events.
    """
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" not in ctype:
        try:
            return resp.json()
        except Exception:
            pass

    text_parts = []
    final_msg = {}
    for raw_line in resp.text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except Exception:
            continue
        etype = evt.get("type")
        if etype == "message_start":
            final_msg = dict(evt.get("message", {}))
        elif etype == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") in ("text_delta", "text"):
                text_parts.append(delta.get("text", ""))
        elif etype == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text" and block.get("text"):
                text_parts.append(block["text"])

    final_msg["content"] = [{"type": "text", "text": "".join(text_parts)}]
    return final_msg


async def call_claude(
    prompt: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    auth_token: Optional[str] = None,
    max_tokens: int = 1024,
    timeout: float = 30.0,
) -> Dict:
    """Call Claude and parse strict JSON output.

    Returns the parsed dict, or a deterministic fallback on any error.
    """
    model = model or settings.CLAUDE_MODEL
    base_url = (base_url or settings.ANTHROPIC_BASE_URL).rstrip("/")
    # The base URL may or may not already include a trailing /v1 (9Router and
    # some gateways are configured with it). Normalize so we never emit
    # .../v1/v1/messages, which 404s and silently triggers the fallback.
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    auth_token = auth_token or settings.ANTHROPIC_AUTH_TOKEN

    if not auth_token:
        return _fallback(prompt)

    url = f"{base_url}/v1/messages"
    headers = {
        "x-api-key": auth_token,
        "authorization": f"Bearer {auth_token}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": False,
        "system": (
            "You are a financial signal analyst. Output ONLY a single valid "
            "JSON object. No prose, no markdown, no code fences, no commentary "
            "before or after. The response MUST start with { and end with }."
        ),
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = _decode_response(resp)
        text = _extract_text(data)
        if not text:
            logger.warning("call_claude(%s): empty response text", model)
            return _fallback(prompt)
        return _parse_json_loose(text)
    except httpx.HTTPStatusError as exc:
        logger.warning("call_claude(%s) HTTP %s: %s", model,
                       exc.response.status_code, exc.response.text[:300])
        return _fallback(prompt)
    except Exception as exc:
        logger.warning("call_claude(%s) failed: %s: %s", model,
                       type(exc).__name__, exc)
        return _fallback(prompt)
