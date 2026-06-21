"""APScheduler jobs. All times are WIB (UTC+7)."""
from __future__ import annotations

import logging

from app.data.universe import load_universe
from app.signals.generator import generate_signals

logger = logging.getLogger(__name__)

# WIB = UTC+7. APScheduler cron is configured with an explicit timezone below.
try:
    from zoneinfo import ZoneInfo

    WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # pragma: no cover
    WIB = "Asia/Jakarta"


async def _scan_and_log(tag: str, top_n: int = 5, limit: int = 15) -> None:
    universe = load_universe()[:limit]
    signals = await generate_signals(universe, top_n=top_n)
    logger.info("[%s] generated %d signals", tag, len(signals))


async def premarket() -> None:
    """08:30 WIB pre-market scan."""
    await _scan_and_log("premarket")


async def opening() -> None:
    """09:15 WIB opening momentum scan."""
    await _scan_and_log("opening")


async def intraday() -> None:
    """Every 5 minutes 09:00-16:00 WIB."""
    await _scan_and_log("intraday", top_n=3, limit=10)


async def midday() -> None:
    """13:00 WIB midday scan."""
    await _scan_and_log("midday")


async def closing() -> None:
    """15:45 WIB closing watch."""
    await _scan_and_log("closing")


async def eod() -> None:
    """16:30 WIB end-of-day report."""
    await _scan_and_log("eod", top_n=10, limit=30)


def build_scheduler():
    """Create an AsyncIOScheduler with all jobs registered (WIB)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone=WIB)

    scheduler.add_job(premarket, CronTrigger(hour=8, minute=30, timezone=WIB), id="premarket")
    scheduler.add_job(opening, CronTrigger(hour=9, minute=15, timezone=WIB), id="opening")
    scheduler.add_job(
        intraday,
        CronTrigger(hour="9-15", minute="*/5", timezone=WIB),
        id="intraday",
    )
    scheduler.add_job(midday, CronTrigger(hour=13, minute=0, timezone=WIB), id="midday")
    scheduler.add_job(closing, CronTrigger(hour=15, minute=45, timezone=WIB), id="closing")
    scheduler.add_job(eod, CronTrigger(hour=16, minute=30, timezone=WIB), id="eod")

    return scheduler
