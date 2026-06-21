"""Persist signals and track their performance."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Signal, SignalUpdate, Tracking, async_session

logger = logging.getLogger(__name__)


async def save_signal(db: AsyncSession, signal: Dict) -> Signal:
    """Persist a generated signal dict (legacy API, session injected)."""
    import json
    reasons = signal.get("reasons", [])
    action = signal.get("action", signal.get("label", "HOLD"))
    sl_val = float(signal.get("stop_loss", signal.get("sl", 0.0)))
    row = Signal(
        symbol=signal["symbol"],
        action=action,
        label=action,
        score=float(signal.get("score", 0.0)),
        entry=float(signal.get("entry", 0.0)),
        tp1=float(signal.get("tp1", 0.0)),
        tp2=float(signal.get("tp2", 0.0)),
        stop_loss=sl_val,
        sl=sl_val,
        confidence=float(signal.get("confidence", 0.0)),
        reasons=json.dumps(reasons, ensure_ascii=False),
        summary=signal.get("summary", ""),
        chart_path=signal.get("chart_path", ""),
        status="open",
    )
    db.add(row)
    await db.flush()
    track = Tracking(
        signal_id=row.id,
        symbol=row.symbol,
        entry=row.entry,
        current_price=row.entry,
        pnl_pct=0.0,
        status="OPEN",
    )
    db.add(track)
    await db.commit()
    await db.refresh(row)
    return row


async def update_tracking(
    db: AsyncSession, signal_id: int, current_price: float
) -> Optional[Tracking]:
    """Update the tracking row for a signal with the latest price."""
    result = await db.execute(select(Tracking).where(Tracking.signal_id == signal_id))
    track = result.scalar_one_or_none()
    if track is None:
        return None

    track.current_price = float(current_price)
    if track.entry:
        track.pnl_pct = round((current_price - track.entry) / track.entry * 100.0, 2)

    sig_result = await db.execute(select(Signal).where(Signal.id == signal_id))
    sig = sig_result.scalar_one_or_none()
    if sig:
        sl = sig.stop_loss or sig.sl
        if sig.tp2 and current_price >= sig.tp2:
            track.status = "TP2_HIT"
            sig.status = "tp2"
        elif sig.tp1 and current_price >= sig.tp1:
            track.status = "TP1_HIT"
            sig.status = "tp1"
        elif sl and current_price <= sl:
            track.status = "SL_HIT"
            sig.status = "stopped"

    await db.commit()
    await db.refresh(track)
    return track


async def update_all_open_signals() -> Dict:
    """Fetch latest price for all open signals and update tracking."""
    from app.data.fetch_yahoo import fetch_ohlcv

    async with async_session() as db:
        result = await db.execute(
            select(Signal).where(Signal.status == "open")
        )
        open_signals = result.scalars().all()

    updated = 0
    errors = 0
    for sig in open_signals:
        try:
            df = fetch_ohlcv(sig.symbol, period="5d")
            if df.empty:
                continue
            latest_close = float(df["close"].iloc[-1])
            latest_high = float(df["high"].max())
            latest_low = float(df["low"].min())

            # compute holding days
            created = sig.created_at
            days = 0
            if created:
                days = (datetime.utcnow() - created).days

            await _update_signal_full(
                sig.id,
                last_price=latest_close,
                max_price=latest_high,
                min_price=latest_low,
                holding_days=days,
                entry=sig.entry,
                tp1=sig.tp1,
                tp2=sig.tp2,
                stop_loss=sig.stop_loss or sig.sl,
            )
            updated += 1
        except Exception as exc:
            logger.warning("tracker error for %s: %s", sig.symbol, exc)
            errors += 1

    return {"updated": updated, "errors": errors, "total": len(open_signals)}


async def _update_signal_full(
    signal_id: int,
    last_price: float,
    max_price: float,
    min_price: float,
    holding_days: int,
    entry: float,
    tp1: float,
    tp2: float,
    stop_loss: float,
) -> None:
    """Write a SignalUpdate row and update Signal + Tracking status."""
    new_status = "open"
    return_pct = 0.0
    if entry and entry > 0:
        return_pct = round((last_price - entry) / entry * 100.0, 2)
    if tp2 and last_price >= tp2:
        new_status = "tp2"
    elif tp1 and last_price >= tp1:
        new_status = "tp1"
    elif stop_loss and last_price <= stop_loss:
        new_status = "stopped"

    async with async_session() as db:
        # update Signal
        sig_res = await db.execute(select(Signal).where(Signal.id == signal_id))
        sig = sig_res.scalar_one_or_none()
        if sig:
            sig.status = new_status

        # update Tracking
        track_res = await db.execute(
            select(Tracking).where(Tracking.signal_id == signal_id)
        )
        track = track_res.scalar_one_or_none()
        if track:
            track.current_price = last_price
            if entry:
                track.pnl_pct = return_pct
            status_map = {"tp2": "TP2_HIT", "tp1": "TP1_HIT", "stopped": "SL_HIT", "open": "OPEN"}
            track.status = status_map.get(new_status, "OPEN")

        # write update row
        su = SignalUpdate(
            signal_id=signal_id,
            checked_at=datetime.utcnow().isoformat(),
            last_price=last_price,
            max_price=max_price,
            min_price=min_price,
            status=new_status,
            return_pct=return_pct,
            holding_days=holding_days,
        )
        db.add(su)
        await db.commit()


async def get_performance_summary() -> Dict:
    """Return aggregate performance metrics."""
    from sqlalchemy import func
    from app.db import async_session as session_factory
    async with session_factory() as db:
        total = (await db.execute(select(func.count(Tracking.id)))).scalar() or 0
        avg_pnl = (await db.execute(select(func.avg(Tracking.pnl_pct)))).scalar() or 0.0
        wins = (
            await db.execute(select(func.count(Tracking.id)).where(Tracking.pnl_pct > 0))
        ).scalar() or 0
        open_count = (
            await db.execute(select(func.count(Signal.id)).where(Signal.status == "open"))
        ).scalar() or 0
        tp1_hit = (
            await db.execute(select(func.count(Tracking.id)).where(Tracking.status == "TP1_HIT"))
        ).scalar() or 0
        tp2_hit = (
            await db.execute(select(func.count(Tracking.id)).where(Tracking.status == "TP2_HIT"))
        ).scalar() or 0
        sl_hit = (
            await db.execute(select(func.count(Tracking.id)).where(Tracking.status == "SL_HIT"))
        ).scalar() or 0

    win_rate = round(wins / total * 100.0, 1) if total else 0.0
    return {
        "total": total,
        "open_count": open_count,
        "win_rate_pct": win_rate,
        "avg_pnl_pct": round(float(avg_pnl), 2),
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "sl_hit": sl_hit,
    }
