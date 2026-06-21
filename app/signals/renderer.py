"""Render signals into delivery text (Telegram / WhatsApp)."""
from __future__ import annotations

from typing import Dict, List

LABEL_EMOJI = {
    "BUY": "🟢",
    "WATCH": "🟡",
    "HOLD": "⚪",
    "AVOID": "🟠",
    "DANGER": "🔴",
}

ACTION_ID = {
    "BUY": "BELI",
    "WATCH": "PANTAU",
    "HOLD": "TAHAN",
    "AVOID": "HINDARI",
    "DANGER": "BAHAYA",
}


def _fmt_price(v: object) -> str:
    if v is None:
        return "-"
    try:
        fv = float(v)
        if fv == 0:
            return "-"
        if fv >= 1000:
            return f"{fv:,.0f}"
        return f"{fv:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def format_telegram_message(signal: Dict, data_date: str = "") -> str:
    """Format a signal dict into a Markdown-compatible Telegram message."""
    sym = signal.get("symbol", "?")
    action = signal.get("action", signal.get("label", "HOLD"))
    emoji = LABEL_EMOJI.get(action, "⚪")
    action_id = ACTION_ID.get(action, action)
    score = signal.get("score", 0)
    conf = int(float(signal.get("confidence", 0)) * 100)

    entry = _fmt_price(signal.get("entry"))
    tp1 = _fmt_price(signal.get("tp1"))
    tp2 = _fmt_price(signal.get("tp2"))
    sl = _fmt_price(signal.get("stop_loss") or signal.get("sl"))
    rr = signal.get("risk_reward")

    lines = [
        f"{emoji} *{sym}* — *{action_id}*",
        f"Skor: {score}/100  |  Confidence: {conf}%",
        "",
        f"📌 Entry: Rp {entry}",
        f"🎯 TP1: Rp {tp1}",
        f"🎯 TP2: Rp {tp2}",
        f"🛑 Stop Loss: Rp {sl}",
    ]

    if rr:
        lines.append(f"⚖️ Risk/Reward: {rr:.1f}x")

    summary = signal.get("summary")
    if summary:
        lines += ["", f"_{summary}_"]

    reasons = signal.get("reasons") or []
    if reasons:
        lines += ["", "*📊 Alasan:*"]
        lines += [f"• {r}" for r in reasons[:5]]

    reason_codes = signal.get("reason_codes") or []
    if reason_codes:
        tag_str = "  ".join(f"`{c}`" for c in reason_codes[:6])
        lines += ["", tag_str]

    if data_date:
        lines += ["", f"_Data: {data_date}_"]

    lines += [
        "",
        "_⚠️ Disclaimer: Bukan ajakan beli/jual. Gunakan manajemen risiko._",
    ]
    return "\n".join(lines)


def format_whatsapp_message(signal: Dict, data_date: str = "") -> str:
    """Format a signal dict as plain text for WhatsApp."""
    sym = signal.get("symbol", "?")
    action = signal.get("action", signal.get("label", "HOLD"))
    emoji = LABEL_EMOJI.get(action, "⚪")
    action_id = ACTION_ID.get(action, action)
    score = signal.get("score", 0)
    conf = int(float(signal.get("confidence", 0)) * 100)

    entry = _fmt_price(signal.get("entry"))
    tp1 = _fmt_price(signal.get("tp1"))
    tp2 = _fmt_price(signal.get("tp2"))
    sl = _fmt_price(signal.get("stop_loss") or signal.get("sl"))

    lines = [
        f"{emoji} *{sym}* — {action_id}",
        f"Skor: {score}/100 | Confidence: {conf}%",
        "",
        f"Entry: Rp {entry}",
        f"TP1: Rp {tp1}",
        f"TP2: Rp {tp2}",
        f"Stop Loss: Rp {sl}",
    ]

    reasons = signal.get("reasons") or []
    if reasons:
        lines += ["", "Alasan:"]
        lines += [f"- {r}" for r in reasons[:3]]

    if data_date:
        lines += ["", f"Data: {data_date}"]

    lines += ["", "⚠️ Bukan ajakan beli/jual. Manajemen risiko selalu."]
    return "\n".join(lines)


def format_scan_summary(signals: List[Dict], mode: str = "manual") -> str:
    """Format a list of top signals into a Telegram scan summary."""
    if not signals:
        return "Tidak ada sinyal yang memenuhi kriteria saat ini."

    lines = [f"*📡 Scan IDX — {mode.upper()}*", f"Top {len(signals)} sinyal:\n"]
    for i, s in enumerate(signals, 1):
        sym = s.get("symbol", "?")
        action = s.get("action", s.get("label", "HOLD"))
        emoji = LABEL_EMOJI.get(action, "⚪")
        score = s.get("score", 0)
        entry = _fmt_price(s.get("entry"))
        sl = _fmt_price(s.get("stop_loss") or s.get("sl"))
        tp1 = _fmt_price(s.get("tp1"))
        lines.append(
            f"{i}. {emoji} *{sym}* {action}  score={score}  "
            f"entry={entry}  tp1={tp1}  sl={sl}"
        )

    lines += ["", "_⚠️ Bukan ajakan beli/jual._"]
    return "\n".join(lines)
