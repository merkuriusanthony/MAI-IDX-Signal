"""Async SQLAlchemy database layer (SQLite via aiosqlite)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class Signal(Base):
    """A generated trading signal."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    scan_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(16))
    # kept for back-compat with old code using .label
    label: Mapped[str] = mapped_column(String(16), default="HOLD")
    timeframe: Mapped[str] = mapped_column(String(16), default="daily")
    entry: Mapped[float] = mapped_column(Float, default=0.0)
    tp1: Mapped[float] = mapped_column(Float, default=0.0)
    tp2: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float] = mapped_column(Float, default=0.0)
    # kept for back-compat
    sl: Mapped[float] = mapped_column(Float, default=0.0)
    invalidation: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    reasons: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    chart_path: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")


class SignalUpdate(Base):
    """Tracks signal performance over time."""

    __tablename__ = "signal_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    checked_at: Mapped[str] = mapped_column(String(32))
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    max_price: Mapped[float] = mapped_column(Float, default=0.0)
    min_price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="open")
    return_pct: Mapped[float] = mapped_column(Float, default=0.0)
    holding_days: Mapped[int] = mapped_column(Integer, default=0)


class Tracking(Base):
    """Legacy tracking table — kept for backward compat."""

    __tablename__ = "tracking"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    entry: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class OHLCVDaily(Base):
    """Daily OHLCV cache."""

    __tablename__ = "ohlcv_daily"
    __table_args__ = (UniqueConstraint("symbol", "date", "source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[str] = mapped_column(String(16), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), default="yahoo")
    created_at: Mapped[str] = mapped_column(String(32))


class ScanRun(Base):
    """Record of a scanner run."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="manual")
    universe_count: Mapped[int] = mapped_column(Integer, default=0)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ScanCandidate(Base):
    """Scored candidate from a scan run."""

    __tablename__ = "scan_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    action: Mapped[str] = mapped_column(String(16), default="HOLD")
    close: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    value_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    rsi: Mapped[float] = mapped_column(Float, default=0.0)
    ma20: Mapped[float] = mapped_column(Float, default=0.0)
    ma50: Mapped[float] = mapped_column(Float, default=0.0)
    ma100: Mapped[float] = mapped_column(Float, default=0.0)
    ma200: Mapped[float] = mapped_column(Float, default=0.0)
    volume_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    reason_codes: Mapped[str] = mapped_column(Text, default="[]")
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")


engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they do not exist."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # ensure data dir exists
        import os
        os.makedirs("data/charts", exist_ok=True)


async def get_session() -> AsyncSession:
    """Yield an async session (FastAPI dependency)."""
    async with async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Helper functions (raw async, no FastAPI dependency injection)
# ---------------------------------------------------------------------------

async def save_ohlcv(symbol: str, rows: List[Dict], source: str = "yahoo") -> None:
    """Upsert OHLCV rows into ohlcv_daily."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    async with async_session() as db:
        for row in rows:
            stmt = sqlite_insert(OHLCVDaily).values(
                symbol=symbol,
                date=str(row["date"])[:10],
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
                source=source,
                created_at=datetime.utcnow().isoformat(),
            ).on_conflict_do_nothing(index_elements=["symbol", "date", "source"])
            await db.execute(stmt)
        await db.commit()


async def load_ohlcv(symbol: str, start: str, end: str) -> List[Dict]:
    """Load cached OHLCV rows for symbol between start and end dates."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(OHLCVDaily)
            .where(OHLCVDaily.symbol == symbol)
            .where(OHLCVDaily.date >= start)
            .where(OHLCVDaily.date <= end)
            .order_by(OHLCVDaily.date)
        )
        rows = result.scalars().all()
        return [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]


async def create_scan_run(mode: str, universe_count: int) -> int:
    """Create a new scan run and return its id."""
    async with async_session() as db:
        run = ScanRun(
            started_at=datetime.utcnow().isoformat(),
            mode=mode,
            universe_count=universe_count,
            status="running",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def finish_scan_run(
    scan_run_id: int,
    status: str,
    scanned: int = 0,
    passed: int = 0,
    failed: int = 0,
    error: Optional[str] = None,
) -> None:
    """Mark a scan run as finished."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(ScanRun).where(ScanRun.id == scan_run_id))
        run = result.scalar_one_or_none()
        if run:
            run.finished_at = datetime.utcnow().isoformat()
            run.status = status
            run.scanned_count = scanned
            run.passed_count = passed
            run.failed_count = failed
            run.error = error
            await db.commit()


async def save_scan_candidate(scan_run_id: int, candidate: Dict) -> int:
    """Persist a scored candidate and return its id."""
    async with async_session() as db:
        row = ScanCandidate(
            scan_run_id=scan_run_id,
            symbol=candidate.get("symbol", ""),
            score=float(candidate.get("score", 0)),
            action=candidate.get("action", candidate.get("label", "HOLD")),
            close=float(candidate.get("close", 0)),
            volume=int(candidate.get("volume", 0)),
            value_estimate=float(candidate.get("value_estimate", 0)),
            rsi=float(candidate.get("rsi", 0)),
            ma20=float(candidate.get("ma20", 0)),
            ma50=float(candidate.get("ma50", 0)),
            ma100=float(candidate.get("ma100", 0)),
            ma200=float(candidate.get("ma200", 0)),
            volume_ratio=float(candidate.get("volume_ratio", 0)),
            risk_score=float(candidate.get("risk_score", 0)),
            reason_codes=json.dumps(candidate.get("reason_codes", []), ensure_ascii=False),
            snapshot_json=json.dumps(candidate.get("snapshot", {}), ensure_ascii=False),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def save_signal_dict(signal: Dict, scan_run_id: Optional[int] = None) -> int:
    """Persist a signal dict to the signals table and return id."""
    reasons = signal.get("reasons", [])
    async with async_session() as db:
        action = signal.get("action", signal.get("label", "HOLD"))
        sl_val = float(signal.get("stop_loss", signal.get("sl", 0.0)))
        row = Signal(
            scan_run_id=scan_run_id,
            symbol=signal["symbol"],
            action=action,
            label=action,
            timeframe=signal.get("timeframe", "daily"),
            entry=float(signal.get("entry", 0.0)),
            tp1=float(signal.get("tp1", 0.0)),
            tp2=float(signal.get("tp2", 0.0)),
            stop_loss=sl_val,
            sl=sl_val,
            invalidation=float(signal.get("invalidation", 0.0)),
            confidence=float(signal.get("confidence", 0.0)),
            score=float(signal.get("score", 0.0)),
            reasoning=signal.get("reasoning", signal.get("summary", "")),
            reasons=json.dumps(reasons, ensure_ascii=False),
            summary=signal.get("summary", ""),
            snapshot_json=json.dumps(signal.get("snapshot", {}), ensure_ascii=False),
            chart_path=signal.get("chart_path", ""),
            status="open",
        )
        db.add(row)
        await db.flush()
        # seed tracking row
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
        return row.id


async def list_latest_signals(limit: int = 50) -> List[Dict]:
    """Return latest signals as list of dicts."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(Signal).order_by(Signal.created_at.desc()).limit(limit)
        )
        rows = result.scalars().all()
        out = []
        for r in rows:
            try:
                reasons = json.loads(r.reasons) if r.reasons else []
            except Exception:
                reasons = []
            out.append({
                "id": r.id,
                "symbol": r.symbol,
                "action": r.action,
                "label": r.label,
                "score": r.score,
                "entry": r.entry,
                "tp1": r.tp1,
                "tp2": r.tp2,
                "sl": r.sl,
                "stop_loss": r.stop_loss,
                "confidence": r.confidence,
                "reasons": reasons,
                "summary": r.summary,
                "chart_path": r.chart_path,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            })
        return out


async def update_signal_status(signal_id: int, update: Dict) -> None:
    """Update signal status and add a signal_update row."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(Signal).where(Signal.id == signal_id))
        sig = result.scalar_one_or_none()
        if sig and "status" in update:
            sig.status = update["status"]
        # write update row
        su = SignalUpdate(
            signal_id=signal_id,
            checked_at=datetime.utcnow().isoformat(),
            last_price=float(update.get("last_price", 0)),
            max_price=float(update.get("max_price", 0)),
            min_price=float(update.get("min_price", 0)),
            status=update.get("status", "open"),
            return_pct=float(update.get("return_pct", 0)),
            holding_days=int(update.get("holding_days", 0)),
        )
        db.add(su)
        # also update legacy tracking
        track_result = await db.execute(
            select(Tracking).where(Tracking.signal_id == signal_id)
        )
        track = track_result.scalar_one_or_none()
        if track and "last_price" in update:
            track.current_price = float(update["last_price"])
            if track.entry:
                track.pnl_pct = round(
                    (track.current_price - track.entry) / track.entry * 100.0, 2
                )
            if sig:
                if sig.tp2 and track.current_price >= sig.tp2:
                    track.status = "TP2_HIT"
                elif sig.tp1 and track.current_price >= sig.tp1:
                    track.status = "TP1_HIT"
                elif sig.stop_loss and track.current_price <= sig.stop_loss:
                    track.status = "SL_HIT"
        await db.commit()
