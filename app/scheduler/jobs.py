"""APScheduler jobs. All times are WIB (UTC+7)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB = "Asia/Jakarta"


async def _scan_and_notify(tag: str, top_n: int = 5, limit: int = 0) -> None:
    from app.db import init_db
    await init_db()
    from app.scanner import ScannerService
    scanner = ScannerService(mode=tag, top_n=top_n, limit=limit or None, generate_charts=True)
    result = await scanner.run()
    signals = result.get("top_signals", [])
    logger.info("[%s] generated %d signals (scanned=%d)", tag, len(signals), result.get("scanned", 0))

    # Telegram notify if bot token configured
    from app.config import settings
    if settings.TELEGRAM_BOT_TOKEN and signals:
        try:
            from app.signals.renderer import format_scan_summary
            text = format_scan_summary(signals, mode=tag)
            chat_id = settings.effective_telegram_chat_id()
            if chat_id:
                from telegram import Bot
                bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception as exc:
            logger.warning("Telegram notify error: %s", exc)


async def _tracker_job() -> None:
    """Update all open signal statuses."""
    from app.signals.tracker import update_all_open_signals
    result = await update_all_open_signals()
    logger.info("[tracker] updated=%d errors=%d", result.get("updated", 0), result.get("errors", 0))


async def premarket() -> None:
    """08:30 WIB pre-market scan."""
    await _scan_and_notify("premarket")


async def opening() -> None:
    """09:15 WIB opening momentum scan."""
    await _scan_and_notify("opening")


async def intraday() -> None:
    """Every 30 minutes 09:00-16:00 WIB (daily data fallback)."""
    await _scan_and_notify("intraday", top_n=3, limit=30)


async def midday() -> None:
    """13:00 WIB midday scan."""
    await _scan_and_notify("midday")


async def closing() -> None:
    """15:45 WIB closing watch."""
    await _scan_and_notify("closing")


async def eod() -> None:
    """16:30 WIB end-of-day report + tracker update."""
    await _scan_and_notify("eod", top_n=10)
    await _tracker_job()


def build_scheduler():
    """Create an AsyncIOScheduler with all jobs registered (WIB)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone=WIB)

    scheduler.add_job(premarket, CronTrigger(hour=8, minute=30, timezone=WIB), id="premarket")
    scheduler.add_job(opening, CronTrigger(hour=9, minute=15, timezone=WIB), id="opening")
    scheduler.add_job(
        intraday,
        CronTrigger(hour="9-15", minute="*/30", timezone=WIB),
        id="intraday",
    )
    scheduler.add_job(midday, CronTrigger(hour=13, minute=0, timezone=WIB), id="midday")
    scheduler.add_job(closing, CronTrigger(hour=15, minute=45, timezone=WIB), id="closing")
    scheduler.add_job(eod, CronTrigger(hour=16, minute=30, timezone=WIB), id="eod")

    return scheduler
