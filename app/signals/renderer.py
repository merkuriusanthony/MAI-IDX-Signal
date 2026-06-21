"""Render signals into delivery text (Telegram/WhatsApp)."""
from __future__ import annotations

from typing import Dict

LABEL_EMOJI = {
    "BUY": "🟢",
    "WATCH": "🟡",
    "HOLD": "⚪",
    "AVOID": "🟠",
    "DANGER": "🔴",
}


def format_telegram_message(signal: Dict) -> str:
    """Format a signal dict into a Markdown-ish Telegram message."""
    sym = signal.get("symbol", "?")
    label = signal.get("label", "HOLD")
    emoji = LABEL_EMOJI.get(label, "⚪")
    score = signal.get("score", 0)
    conf = signal.get("confidence", 0)

    lines = [
        f"{emoji} *{sym}* — *{label}*",
        f"Skor: {score}/100  |  Confidence: {int(float(conf) * 100)}%",
        "",
        f"Entry: {signal.get('entry', '-')}",
        f"TP1: {signal.get('tp1', '-')}",
        f"TP2: {signal.get('tp2', '-')}",
        f"SL: {signal.get('sl', '-')}",
    ]

    summary = signal.get("summary")
    if summary:
        lines += ["", f"_{summary}_"]

    reasons = signal.get("reasons") or []
    if reasons:
        lines += ["", "*Alasan:*"]
        lines += [f"• {r}" for r in reasons[:5]]

    lines += ["", "_Disclaimer: bukan ajakan beli/jual. Gunakan manajemen risiko._"]
    return "\n".join(lines)
