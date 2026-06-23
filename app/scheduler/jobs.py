"""APScheduler jobs. All times are WIB (UTC+7)."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB = "Asia/Jakarta"

async def _scan_and_notify(tag: str, top_n: int = 5, limit: int | None = None) -> None:
    from app.db import init_db
    await init_db()
    from app.scanner import ScannerService
    # limit=None => scan the FULL current universe (whatever the file holds,
    # 655 -> 800+). SCAN_DEV_LIMIT still caps it in dev. The worker pool makes
    # the full scan genuinely parallel.
    scanner = ScannerService(mode=tag, top_n=top_n, limit=limit, generate_charts=True)
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


async def universe_update_job() -> None:
    """07:50 WIB daily universe sync (IPO/delisting) + Telegram notify.

    Runs before the 08:30 pre-market scan so that scan uses the fresh list
    (load_universe re-reads the file each scan — no restart needed). Notifies
    only when symbols were added or removed.
    """
    from app.config import settings
    if not settings.UNIVERSE_AUTOUPDATE_ENABLED:
        logger.info("[universe] auto-update disabled")
        return

    import asyncio as _asyncio
    from app.data.universe_update import update_universe_file

    loop = _asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, update_universe_file)
    except Exception as exc:
        logger.warning("[universe] update error: %s", exc)
        return

    status = result.get("status")
    added = result.get("added", [])
    removed = result.get("removed", [])
    suppressed = result.get("removal_suppressed", [])
    logger.info(
        "[universe] status=%s source=%s +%d -%d (suppressed=%d) (%d->%d)",
        status, result.get("source"), len(added), len(removed), len(suppressed),
        result.get("old_count", 0), result.get("new_count", 0),
    )

    if status != "updated" or (not added and not removed):
        return

    def _fmt(syms: list, cap: int = 30) -> str:
        shown = ", ".join(syms[:cap])
        if len(syms) > cap:
            shown += f", … (+{len(syms) - cap})"
        return shown or "—"

    text = (
        f"🔄 *Universe diperbarui* ({result.get('source')})\n"
        f"Total: {result.get('old_count')} → {result.get('new_count')}\n\n"
        f"🟢 *IPO/baru ({len(added)})*: {_fmt(added)}\n"
        f"🔴 *Delisting ({len(removed)})*: {_fmt(removed)}"
    )
    if suppressed:
        text += (
            f"\n\n⚠️ *Tidak dihapus ({len(suppressed)})* — hilang dari "
            f"{result.get('source')} tapi mungkin cuma suspended; tunggu "
            f"konfirmasi IDX resmi: {_fmt(suppressed, 20)}"
        )
    from app.bots.telegram import send_text_notify
    try:
        await send_text_notify(text)
    except Exception as exc:
        logger.warning("[universe] telegram notify error: %s", exc)


async def _tracker_job() -> None:
    """Update all open signal statuses."""
    from app.signals.tracker import update_all_open_signals
    result = await update_all_open_signals()
    logger.info("[tracker] updated=%d errors=%d", result.get("updated", 0), result.get("errors", 0))


async def pre_market_scan() -> None:
    """08:30 WIB pre-market scan (full universe, top 5)."""
    await _scan_and_notify("premarket", top_n=5)


async def opening_scan() -> None:
    """09:15 WIB opening momentum scan (full universe, top 5)."""
    await _scan_and_notify("opening", top_n=5)


async def eod_scan() -> None:
    """16:05 WIB end-of-day report (full universe, top 10) + tracker update."""
    await _scan_and_notify("eod", top_n=10)
    await _tracker_job()


def build_scheduler():
    """Create an AsyncIOScheduler with weekday jobs registered (WIB)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler(timezone=WIB)

    scheduler.add_job(
        universe_update_job,
        CronTrigger(day_of_week="mon-fri", hour=7, minute=50, timezone=WIB),
        id="universe_update",
    )
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
