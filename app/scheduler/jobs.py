"""APScheduler jobs. All times are WIB (UTC+7)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB = "Asia/Jakarta"

FULL_LIMIT = 655


async def _scan_and_notify(tag: str, top_n: int = 5, limit: int = FULL_LIMIT) -> None:
    from app.db import init_db
    await init_db()
    from app.scanner import ScannerService
    scanner = ScannerService(mode=tag, top_n=top_n, limit=limit or None, generate_charts=True)
    result = await scanner.run()
    signals = result.get("top_signals", [])
    logger.info("[%s] generated %d signals (scanned=%d)", tag, len(signals), result.get("scanned", 0))

    if not signals:
        return

    from app.bots.telegram import send_signal_batch
    try:
        await send_signal_batch(signals, mode=tag)
    except Exception as exc:
        logger.warning("[%s] telegram delivery error: %s", tag, exc)


async def _tracker_job() -> None:
    """Update all open signal statuses."""
    from app.signals.tracker import update_all_open_signals
    result = await update_all_open_signals()
    logger.info("[tracker] updated=%d errors=%d", result.get("updated", 0), result.get("errors", 0))


async def pre_market_scan() -> None:
    """08:30 WIB pre-market scan (full universe, top 5)."""
    await _scan_and_notify("premarket", top_n=5, limit=FULL_LIMIT)


async def opening_scan() -> None:
    """09:15 WIB opening momentum scan (full universe, top 5)."""
    await _scan_and_notify("opening", top_n=5, limit=FULL_LIMIT)


async def eod_scan() -> None:
    """16:05 WIB end-of-day report (full universe, top 10) + tracker update."""
    await _scan_and_notify("eod", top_n=10, limit=FULL_LIMIT)
    await _tracker_job()


def build_scheduler():
    """Create an AsyncIOScheduler with weekday jobs registered (WIB)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone=WIB)

    scheduler.add_job(
        pre_market_scan,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30, timezone=WIB),
        id="pre_market_scan",
    )
    scheduler.add_job(
        opening_scan,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=WIB),
        id="opening_scan",
    )
    scheduler.add_job(
        eod_scan,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=WIB),
        id="eod_scan",
    )
    scheduler.add_job(
        _tracker_job,
        CronTrigger(day_of_week="mon-fri", hour="9-16", minute=0, timezone=WIB),
        id="tracker_hourly",
    )

    return scheduler
