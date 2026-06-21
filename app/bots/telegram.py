"""Telegram bot: command handlers for MAI-IDX-Signal."""
from __future__ import annotations

import json
import logging

from app.config import settings
from app.data.universe import load_universe
from app.signals.generator import generate_signals
from app.signals.renderer import format_telegram_message

logger = logging.getLogger(__name__)

PROGRESS = "Sedang analisa..."


async def signal_command(update, context):
    """/signal TICKER — analyse one ticker."""
    args = getattr(context, "args", []) or []
    if not args:
        await update.message.reply_text("Gunakan: /signal TICKER (cth /signal BBCA)")
        return
    ticker = args[0].upper()
    await update.message.reply_text(f"{PROGRESS} {ticker}")
    signals = await generate_signals([ticker], top_n=1, with_ai=True)
    if not signals:
        await update.message.reply_text(f"Tidak ada data untuk {ticker}.")
        return
    await update.message.reply_text(
        format_telegram_message(signals[0]), parse_mode="Markdown"
    )


async def scan_command(update, context):
    """/scan — scan the universe and return top signals."""
    await update.message.reply_text(PROGRESS)
    universe = load_universe()[:10]
    signals = await generate_signals(universe, top_n=5, with_ai=False)
    if not signals:
        await update.message.reply_text("Tidak ada sinyal.")
        return
    for sig in signals:
        await update.message.reply_text(
            format_telegram_message(sig), parse_mode="Markdown"
        )


async def why_command(update, context):
    """/why TICKER — explain the reasoning for a ticker."""
    args = getattr(context, "args", []) or []
    if not args:
        await update.message.reply_text("Gunakan: /why TICKER")
        return
    ticker = args[0].upper()
    await update.message.reply_text(f"{PROGRESS} {ticker}")
    signals = await generate_signals([ticker], top_n=1, with_ai=True)
    if not signals:
        await update.message.reply_text(f"Tidak ada data untuk {ticker}.")
        return
    sig = signals[0]
    reasons = "\n".join(f"• {r}" for r in sig.get("reasons", [])[:6])
    summary = sig.get("summary", "")
    await update.message.reply_text(f"*{ticker}*\n{summary}\n\n{reasons}", parse_mode="Markdown")


async def track_command(update, context):
    """/track — show open tracking summary (placeholder)."""
    await update.message.reply_text(
        "Tracking aktif. Lihat dashboard /dashboard/performance untuk detail."
    )


async def health_command(update, context):
    """/health — liveness check."""
    await update.message.reply_text("OK — MAI-IDX-Signal v0.1.0")


def build_application():
    """Build and return a python-telegram-bot Application with handlers."""
    from telegram.ext import ApplicationBuilder, CommandHandler

    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("why", why_command))
    app.add_handler(CommandHandler("track", track_command))
    app.add_handler(CommandHandler("health", health_command))
    return app


def run() -> None:
    """Run the bot in long-polling mode."""
    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    run()
