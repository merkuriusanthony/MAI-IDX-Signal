"""Async SQLAlchemy database layer (SQLite via aiosqlite)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
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


class BacktestRun(Base):
    """A backtest run over a set of symbols."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(64), default="default")
    universe_size: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    total_signals: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_return: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    created_at: Mapped[str] = mapped_column(String(32), default="")
    summary_json: Mapped[str] = mapped_column(Text, default="{}")


class BacktestResult(Base):
    """A single simulated trade from a backtest run."""

    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    entry_date: Mapped[str] = mapped_column(String(16), default="")
    exit_date: Mapped[str] = mapped_column(String(16), default="")
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float] = mapped_column(Float, default=0.0)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str] = mapped_column(String(16), default="expired")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    sector: Mapped[str] = mapped_column(String(64), default="Unknown")


class User(Base):
    """A subscriber/user with an access tier."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    full_name: Mapped[str] = mapped_column(String(128), default="")
    tier: Mapped[str] = mapped_column(String(16), default="free")  # free/pro/admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[str] = mapped_column(String(32), default="")
    expires_at: Mapped[str] = mapped_column(String(32), default="")  # pro expiry
    signal_count: Mapped[int] = mapped_column(Integer, default=0)  # signals sent


_connect_args = (
    {"timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {}
)


def _ensure_sqlite_parent_dirs() -> None:
    """Ensure relative/absolute SQLite database parent dirs exist before first connect."""
    import os
    from urllib.parse import urlparse

    os.makedirs(settings.CHART_DIR, exist_ok=True)
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return
    parsed = urlparse(url)
    db_path = parsed.path
    if parsed.netloc:
        db_path = f"/{parsed.netloc}{parsed.path}"
    if db_path.startswith("/") and not url.startswith("sqlite+aiosqlite:////"):
        # sqlite:///./data/foo.db parses as /./data/foo.db; treat as relative.
        db_path = db_path.lstrip("/")
    if db_path and db_path not in {":memory:", "/:memory:"}:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)


_ensure_sqlite_parent_dirs()
engine = create_async_engine(
    settings.DATABASE_URL, echo=False, future=True, connect_args=_connect_args
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables if they do not exist."""
    _ensure_sqlite_parent_dirs()
    async with engine.begin() as conn:
        # WAL lets background backtest writers and API readers coexist
        # without "database is locked" under SQLite.
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA busy_timeout=30000")
        await conn.run_sync(Base.metadata.create_all)


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


async def create_backtest_run(
    strategy: str,
    universe_size: int,
    start_date: str = "",
    end_date: str = "",
    status: str = "running",
) -> int:
    """Create a backtest run row and return its id.

    status defaults to "running" for back-compat; pass "queued" for the
    non-blocking background flow.
    """
    async with async_session() as db:
        run = BacktestRun(
            strategy=strategy,
            universe_size=universe_size,
            start_date=start_date,
            end_date=end_date,
            status=status,
            created_at=datetime.utcnow().isoformat(),
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def set_backtest_run_status(run_id: int, status: str) -> None:
    """Update only the status of a backtest run (lifecycle transition)."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = status
            await db.commit()


async def fail_backtest_run(run_id: int, error: str = "") -> None:
    """Mark a backtest run as failed, recording the error in summary_json."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "failed"
            run.summary_json = json.dumps({"error": error}, ensure_ascii=False)
            await db.commit()


async def save_backtest_result(run_id: int, result: Dict) -> int:
    """Persist one simulated trade and return its id."""
    async with async_session() as db:
        row = BacktestResult(
            run_id=run_id,
            symbol=result.get("symbol", ""),
            entry_date=str(result.get("entry_date", ""))[:16],
            exit_date=str(result.get("exit_date", ""))[:16],
            entry_price=float(result.get("entry_price", 0.0)),
            exit_price=float(result.get("exit_price", 0.0)),
            pnl_pct=float(result.get("pnl_pct", 0.0)),
            outcome=result.get("outcome", "expired"),
            score=float(result.get("score", 0.0)),
            sector=result.get("sector", "Unknown"),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def finish_backtest_run(run_id: int, summary: Dict) -> None:
    """Mark a backtest run finished and store summary metrics."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
        run = result.scalar_one_or_none()
        if run:
            run.status = "completed"
            run.total_signals = int(summary.get("total_signals", 0))
            run.win_rate = float(summary.get("win_rate", 0.0))
            run.avg_return = float(summary.get("avg_return", 0.0))
            run.max_drawdown = float(summary.get("max_equity_drawdown", summary.get("max_drawdown", 0.0)))
            run.summary_json = json.dumps(summary, ensure_ascii=False)
            await db.commit()


async def get_backtest_results(run_id: Optional[int] = None) -> List[Dict]:
    """Return backtest result rows; latest run if run_id is None."""
    from sqlalchemy import select
    async with async_session() as db:
        rid = run_id
        if rid is None:
            latest = await db.execute(
                select(BacktestRun).order_by(BacktestRun.id.desc()).limit(1)
            )
            run = latest.scalar_one_or_none()
            if run is None:
                return []
            rid = run.id
        result = await db.execute(
            select(BacktestResult)
            .where(BacktestResult.run_id == rid)
            .order_by(BacktestResult.id)
        )
        rows = result.scalars().all()
        return [
            {
                "run_id": r.run_id,
                "symbol": r.symbol,
                "entry_date": r.entry_date,
                "exit_date": r.exit_date,
                "entry_price": r.entry_price,
                "exit_price": r.exit_price,
                "pnl_pct": r.pnl_pct,
                "outcome": r.outcome,
                "score": r.score,
                "sector": r.sector,
            }
            for r in rows
        ]


async def get_backtest_run(run_id: int) -> Optional[Dict]:
    """Return one backtest run as a dict, or None if missing."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
        r = result.scalar_one_or_none()
        if r is None:
            return None
        try:
            summary = json.loads(r.summary_json) if r.summary_json else {}
        except Exception:
            summary = {}
        return {
            "id": r.id,
            "strategy": r.strategy,
            "universe_size": r.universe_size,
            "total_signals": r.total_signals,
            "win_rate": r.win_rate,
            "avg_return": r.avg_return,
            "max_drawdown": r.max_drawdown,
            "status": r.status,
            "created_at": r.created_at,
            "summary": summary,
        }


async def list_backtest_runs(limit: int = 20) -> List[Dict]:
    """Return latest backtest runs as dicts."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "strategy": r.strategy,
                "universe_size": r.universe_size,
                "total_signals": r.total_signals,
                "win_rate": r.win_rate,
                "avg_return": r.avg_return,
                "max_drawdown": r.max_drawdown,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ]


async def create_user(
    telegram_id: int,
    username: str = "",
    full_name: str = "",
    tier: str = "free",
) -> int:
    """Create a user row and return its id (no-op id if already exists)."""
    existing = await get_user_by_telegram_id(telegram_id)
    if existing is not None:
        return existing.id
    async with async_session() as db:
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            tier=tier,
            active=True,
            joined_at=datetime.utcnow().isoformat(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id


async def get_user_by_telegram_id(telegram_id: int) -> Optional["User"]:
    """Return the User for a telegram_id, or None."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


async def set_user_tier(telegram_id: int, tier: str, expires_at: str = "") -> bool:
    """Set a user's tier. Returns True if the user existed."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return False
        user.tier = tier
        if expires_at:
            user.expires_at = expires_at
        await db.commit()
        return True


async def increment_signal_count(telegram_id: int, amount: int = 1) -> None:
    """Increment a user's daily signal counter."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is not None:
            user.signal_count = (user.signal_count or 0) + amount
            await db.commit()


async def reset_signal_counts() -> None:
    """Reset all users' daily signal counters to zero."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(User))
        for user in result.scalars().all():
            user.signal_count = 0
        await db.commit()


async def list_users(limit: int = 200) -> List[Dict]:
    """Return users as dicts for admin views."""
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(User).order_by(User.id.desc()).limit(limit))
        rows = result.scalars().all()
        return [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "full_name": u.full_name,
                "tier": u.tier,
                "active": u.active,
                "joined_at": u.joined_at,
                "expires_at": u.expires_at,
                "signal_count": u.signal_count,
            }
            for u in rows
        ]


_STATUS_TABLES = [
    "signals",
    "scan_runs",
    "scan_candidates",
    "backtest_runs",
    "backtest_results",
    "users",
]


async def get_db_status() -> Dict[str, Any]:
    """Report DB connectivity, key table presence, and cheap latest metadata.

    Never raises — failures are reported in the returned dict so /api/status
    and /dashboard/status stay up even when the DB is missing or corrupt.
    """
    from sqlalchemy import func, select, text

    status: Dict[str, Any] = {
        "connected": False,
        "url": settings.DATABASE_URL,
        "tables": {},
        "signal_count": 0,
        "latest_signal_at": None,
        "latest_scan": None,
        "error": None,
    }
    try:
        async with async_session() as db:
            # connectivity
            await db.execute(text("SELECT 1"))
            status["connected"] = True

            # which of the known tables exist
            res = await db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            present = {row[0] for row in res.fetchall()}
            status["tables"] = {t: (t in present) for t in _STATUS_TABLES}

            if "signals" in present:
                status["signal_count"] = (
                    await db.execute(select(func.count(Signal.id)))
                ).scalar() or 0
                latest = (
                    await db.execute(
                        select(Signal).order_by(Signal.created_at.desc()).limit(1)
                    )
                ).scalar_one_or_none()
                if latest is not None:
                    status["latest_signal_at"] = (
                        latest.created_at.isoformat() if latest.created_at else None
                    )

            if "scan_runs" in present:
                run = (
                    await db.execute(
                        select(ScanRun).order_by(ScanRun.id.desc()).limit(1)
                    )
                ).scalar_one_or_none()
                if run is not None:
                    status["latest_scan"] = {
                        "id": run.id,
                        "mode": run.mode,
                        "status": run.status,
                        "started_at": run.started_at,
                        "finished_at": run.finished_at,
                        "passed_count": run.passed_count,
                        "scanned_count": run.scanned_count,
                    }
    except Exception as exc:  # noqa: BLE001 — surface, never crash the probe
        status["error"] = str(exc)
    return status


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
