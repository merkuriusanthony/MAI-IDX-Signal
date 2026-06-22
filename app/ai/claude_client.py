"""Async Claude client (Anthropic-compatible Messages API).

Falls back to a deterministic template if the API call fails so the pipeline
never blocks on AI availability.
"""
from __future__ import annotations

import json
from typing import Dict, Optional

import httpx

from app.config import settings


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
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = _extract_text(data)
        if not text:
            return _fallback(prompt)
        # Strip markdown fences if present.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
        return json.loads(text)
    except Exception:
        return _fallback(prompt)
