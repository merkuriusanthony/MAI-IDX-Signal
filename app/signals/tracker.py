"""Persist signals and track their performance."""
from __future__ import annotations

import json
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Signal, Tracking


async def save_signal(db: AsyncSession, signal: Dict) -> Signal:
    """Persist a generated signal dict and seed a tracking row."""
    reasons = signal.get("reasons", [])
    row = Signal(
        symbol=signal["symbol"],
        label=signal.get("label", "HOLD"),
        score=float(signal.get("score", 0.0)),
        entry=float(signal.get("entry", 0.0)),
        tp1=float(signal.get("tp1", 0.0)),
        tp2=float(signal.get("tp2", 0.0)),
        sl=float(signal.get("sl", 0.0)),
        confidence=float(signal.get("confidence", 0.0)),
        reasons=json.dumps(reasons, ensure_ascii=False),
        summary=signal.get("summary", ""),
        chart_path=signal.get("chart_path", ""),
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
    result = await db.execute(
        select(Tracking).where(Tracking.signal_id == signal_id)
    )
    track = result.scalar_one_or_none()
    if track is None:
        return None

    track.current_price = float(current_price)
    if track.entry:
        track.pnl_pct = round((current_price - track.entry) / track.entry * 100.0, 2)

    sig_result = await db.execute(select(Signal).where(Signal.id == signal_id))
    sig = sig_result.scalar_one_or_none()
    if sig:
        if sig.tp1 and current_price >= sig.tp1:
            track.status = "TP1_HIT"
        if sig.tp2 and current_price >= sig.tp2:
            track.status = "TP2_HIT"
        if sig.sl and current_price <= sig.sl:
            track.status = "SL_HIT"

    await db.commit()
    await db.refresh(track)
    return track
