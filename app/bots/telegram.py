"""Telegram bot: command handlers for MAI-IDX-Signal."""
from __future__ import annotations

import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)

PROGRESS_SCAN = "📡 Sedang analisa IDX... tunggu 1-2 menit."
PROGRESS_SYM = "📊 Sedang analisa {symbol}... sebentar."


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def health_command(update, context):
    """/health — liveness check."""
    await update.message.reply_text("✅ MAI-IDX-Signal v0.2.0 — OK")


async def signal_command(update, context):
    """/signal TICKER — analyse one ticker."""
    args = getattr(context, "args", []) or []
    if not args:
        await update.message.reply_text("Gunakan: /signal TICKER  (contoh: /signal BBCA)")
        return
    ticker = args[0].upper()
    msg = await update.message.reply_text(PROGRESS_SYM.format(symbol=ticker))

    from app.signals.generator import generate_signal_single
    sig = await generate_signal_single(ticker, with_ai=True)
    if not sig:
        await msg.edit_text(f"❌ Tidak ada data untuk {ticker}.")
        return

    from app.signals.chart import generate_chart
    from app.data.fetch_yahoo import fetch_ohlcv
    df = fetch_ohlcv(ticker)
    chart_path = generate_chart(ticker, df, sig) if not df.empty else ""

    from app.signals.renderer import format_telegram_message
    text = format_telegram_message(sig)

    if chart_path:
        try:
            with open(chart_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=text, parse_mode="Markdown")
            await msg.delete()
            return
        except Exception as exc:
            logger.warning("chart send failed: %s", exc)

    await msg.edit_text(text, parse_mode="Markdown")


async def scan_command(update, context):
    """/scan — scan top signals from IDX universe."""
    msg = await update.message.reply_text(PROGRESS_SCAN)

    from app.db import init_db
    await init_db()

    from app.scanner import ScannerService
    scanner = ScannerService(mode="manual", top_n=5, generate_charts=True)
    result = await scanner.run()
    signals = result.get("top_signals", [])

    if not signals:
        await msg.edit_text("Tidak ada sinyal yang memenuhi kriteria saat ini.")
        return

    from app.signals.renderer import format_scan_summary
    summary = format_scan_summary(signals, mode="manual")
    await msg.edit_text(summary, parse_mode="Markdown")

    # send per-signal charts
    for sig in signals:
        chart_path = sig.get("chart_path", "")
        if not chart_path:
            continue
        try:
            from app.signals.renderer import format_telegram_message
            caption = format_telegram_message(sig)[:1024]
            with open(chart_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode="Markdown")
        except Exception as exc:
            logger.warning("chart send failed for %s: %s", sig.get("symbol"), exc)


async def why_command(update, context):
    """/why TICKER — explain reasoning from last stored signal."""
    args = getattr(context, "args", []) or []
    if not args:
        await update.message.reply_text("Gunakan: /why TICKER")
        return
    ticker = args[0].upper()
    msg = await update.message.reply_text(PROGRESS_SYM.format(symbol=ticker))

    from app.db import list_latest_signals
    all_sigs = await list_latest_signals(limit=200)
    matching = [s for s in all_sigs if s["symbol"] == ticker]

    if matching:
        sig = matching[0]
        reasons = sig.get("reasons", [])
        summary = sig.get("summary", "")
    else:
        # generate fresh
        from app.signals.generator import generate_signal_single
        sig = await generate_signal_single(ticker, with_ai=True)
        if not sig:
            await msg.edit_text(f"❌ Tidak ada data untuk {ticker}.")
            return
        reasons = sig.get("reasons", [])
        summary = sig.get("summary", "")

    action = sig.get("action", "HOLD")
    score = sig.get("score", 0) or 0
    entry = sig.get("entry", 0) or 0
    tp1 = sig.get("tp1", 0) or 0
    sl = sig.get("stop_loss") or sig.get("sl", 0) or 0

    reason_text = "\n".join(f"• {r}" for r in reasons[:8])
    text = f"*{ticker}* — {action} (score {score:.0f}/100)\n\n"
    text += f"Entry: {entry:,.0f} | TP1: {tp1:,.0f} | SL: {sl:,.0f}\n\n"
    if summary:
        text += f"_{summary}_\n\n"
    text += f"*Analisa teknikal:*\n{reason_text}"
    text += "\n\n_⚠️ Bukan ajakan beli/jual._"

    await msg.edit_text(text, parse_mode="Markdown")


async def track_command(update, context):
    """/track — show open signals with live PnL."""
    from app.db import list_latest_signals
    signals = await list_latest_signals(limit=50)
    open_signals = [s for s in signals if s.get("status") == "open"][:10]

    if not open_signals:
        await update.message.reply_text("Tidak ada sinyal aktif saat ini.")
        return

    from app.data.fetch_yahoo import fetch_ohlcv
    lines = ["*📋 Sinyal Aktif + PnL*\n"]
    for s in open_signals:
        entry = s.get("entry", 0) or 0
        try:
            df = fetch_ohlcv(s["symbol"], period="5d")
            price = float(df["close"].iloc[-1]) if not df.empty else entry
        except Exception:
            price = entry
        pnl = (price - entry) / entry * 100 if entry else 0.0
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        lines.append(
            f"{emoji} *{s['symbol']}* {s.get('action','HOLD')} | "
            f"entry {entry:,.0f} | now {price:,.0f} | {pnl:+.1f}%"
        )

    lines.append("\n_Lihat dashboard untuk detail._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Build application
# ---------------------------------------------------------------------------

def build_application():
    """Build and return a python-telegram-bot Application with handlers."""
    from telegram.ext import ApplicationBuilder, CommandHandler

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("why", why_command))
    app.add_handler(CommandHandler("track", track_command))
    return app


def run() -> None:
    """Run the bot in long-polling mode."""
    app = build_application()
    logger.info("Starting Telegram bot polling...")
    app.run_polling()


# ---------------------------------------------------------------------------
# Async lifecycle (for embedding in FastAPI lifespan)
# ---------------------------------------------------------------------------

_PLACEHOLDERS = {"", "changeme", "xxx", "your-token", "your_token_here", "placeholder"}


def token_is_valid(token: str | None) -> bool:
    """True if the token looks real (non-empty, not a placeholder)."""
    t = (token or "").strip()
    return bool(t) and t.lower() not in _PLACEHOLDERS


async def start_bot() -> object | None:
    """Initialize and start the PTB application + updater (non-blocking).

    Returns the running Application, or None if disabled / failed.
    Unlike run_polling(), this does not block — it starts the updater as a
    background task so it can live inside the FastAPI lifespan.
    """
    if not token_is_valid(settings.TELEGRAM_BOT_TOKEN):
        logger.info("Telegram bot disabled (no token)")
        return None
    try:
        app = build_application()
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot started")
        return app
    except Exception as exc:
        logger.warning("Telegram bot failed to start: %s", exc)
        return None


async def stop_bot(app: object | None) -> None:
    """Gracefully stop a running PTB application."""
    if app is None:
        return
    try:
        if getattr(app, "updater", None) and app.updater.running:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Telegram bot stopped")
    except Exception as exc:
        logger.warning("Telegram bot stop error: %s", exc)


# ---------------------------------------------------------------------------
# Outbound batch delivery (for scheduler jobs)
# ---------------------------------------------------------------------------

async def send_signal_batch(signals: list, chat_id: str | None = None, mode: str = "manual") -> int:
    """Send a scan summary + per-signal charts to a Telegram chat.

    Returns the number of messages sent. No-op (returns 0) if the bot token
    or chat id is missing.
    """
    if not token_is_valid(settings.TELEGRAM_BOT_TOKEN):
        logger.info("send_signal_batch skipped: no telegram token")
        return 0
    if not signals:
        return 0
    chat_id = chat_id or settings.effective_telegram_chat_id()
    if not chat_id:
        logger.warning("send_signal_batch skipped: no chat id")
        return 0

    from telegram import Bot
    from app.signals.renderer import format_scan_summary, format_telegram_message

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    sent = 0
    try:
        summary = format_scan_summary(signals, mode=mode)
        await bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown")
        sent += 1
    except Exception as exc:
        logger.warning("send_signal_batch summary error: %s", exc)

    for sig in signals:
        caption = format_telegram_message(sig)[:1024]
        chart_path = sig.get("chart_path", "")
        try:
            if chart_path and os.path.exists(chart_path):
                with open(chart_path, "rb") as photo:
                    await bot.send_photo(
                        chat_id=chat_id, photo=photo, caption=caption, parse_mode="Markdown"
                    )
            else:
                await bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown")
            sent += 1
        except Exception as exc:
            logger.warning("send_signal_batch send error for %s: %s", sig.get("symbol"), exc)
    logger.info("send_signal_batch sent %d messages to %s", sent, chat_id)
    return sent


# ---------------------------------------------------------------------------
# WhatsApp send hook placeholder
# ---------------------------------------------------------------------------

async def send_whatsapp(message: str, target: str | None = None) -> bool:
    """Send a message via WhatsApp bridge.

    Returns True if sent, False if WA is not configured.
    When WHATSAPP_ENABLED=true and a WA bridge URL is configured, this will
    dispatch to it. Otherwise logs and returns False.
    """
    if not settings.WHATSAPP_ENABLED:
        logger.debug("WhatsApp not enabled — skipping send")
        return False

    wa_url = getattr(settings, "WHATSAPP_BRIDGE_URL", "") or ""
    if not wa_url:
        logger.warning("WHATSAPP_ENABLED=true but WHATSAPP_BRIDGE_URL not set")
        return False

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                wa_url,
                json={"message": message, "target": target},
            )
            resp.raise_for_status()
            logger.info("WhatsApp message sent OK")
            return True
    except Exception as exc:
        logger.warning("WhatsApp send failed: %s", exc)
        return False


if __name__ == "__main__":
    run()
