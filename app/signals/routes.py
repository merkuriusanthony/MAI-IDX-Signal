"""Signals + scan API routers."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.data.universe import load_universe
from app.db import list_latest_signals
from app.signals.generator import generate_signal_single, generate_signals

signals_router = APIRouter(prefix="/api/signals", tags=["signals"])
scan_router = APIRouter(prefix="/api/scan", tags=["scan"])
chart_router = APIRouter(prefix="/charts", tags=["charts"])
analyze_router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@analyze_router.post("/{symbol}")
async def analyze_symbol(symbol: str):
    """On-demand deep analysis for one symbol.

    Builds a signal (fetches fundamentals + foreign flow internally),
    renders the 5-panel chart, persists the signal, returns JSON.
    """
    from app.db import init_db, save_signal_dict
    from app.signals.chart import generate_chart

    await init_db()
    sig = await generate_signal_single(symbol.upper())
    if sig is None:
        raise HTTPException(status_code=404, detail=f"No data for {symbol.upper()}")

    df = sig.get("_df")
    if df is not None:
        chart_path = generate_chart(
            symbol.upper(), df, sig,
            fin=sig.get("fin"), foreign_df=sig.get("_foreign_df"),
        )
        sig["chart_path"] = chart_path

    # Strip transient (non-serializable) keys before persist + response.
    sig.pop("_df", None)
    sig.pop("_foreign_df", None)
    sig_id = await save_signal_dict(sig)

    return {
        "signal_id": sig_id,
        "chart_path": sig.get("chart_path", ""),
        "fin": sig.get("fin", {}),
        "snapshot": sig.get("snapshot", {}),
    }


# ---------------------------------------------------------------------------
# Signal routes
# ---------------------------------------------------------------------------

@signals_router.get("/latest")
async def get_latest_signals(limit: int = Query(20, ge=1, le=100)):
    """Return latest persisted signals."""
    signals = await list_latest_signals(limit=limit)
    return {"count": len(signals), "signals": signals}


@signals_router.post("/send-latest")
async def send_latest_signals(limit: int = Query(5, ge=1, le=20), mode: str = "manual"):
    """Read the latest persisted signals and push them to Telegram."""
    signals = await list_latest_signals(limit=limit)
    if not signals:
        return {"sent": 0, "detail": "no signals to send"}
    from app.bots.telegram import send_signal_batch
    sent = await send_signal_batch(signals, mode=mode)
    return {"sent": sent, "count": len(signals)}


@signals_router.get("/{signal_id}")
async def get_signal_by_id(signal_id: int):
    """Return a single persisted signal by id."""
    from sqlalchemy import select
    from app.db import async_session, Signal
    import json
    async with async_session() as db:
        result = await db.execute(select(Signal).where(Signal.id == signal_id))
        sig = result.scalar_one_or_none()
        if sig is None:
            raise HTTPException(status_code=404, detail="Signal not found")
        try:
            reasons = json.loads(sig.reasons) if sig.reasons else []
        except Exception:
            reasons = []
        return {
            "id": sig.id,
            "symbol": sig.symbol,
            "action": sig.action,
            "label": sig.label,
            "score": sig.score,
            "entry": sig.entry,
            "tp1": sig.tp1,
            "tp2": sig.tp2,
            "stop_loss": sig.stop_loss,
            "sl": sig.sl,
            "confidence": sig.confidence,
            "reasons": reasons,
            "summary": sig.summary,
            "chart_path": sig.chart_path,
            "status": sig.status,
            "created_at": sig.created_at.isoformat() if sig.created_at else "",
        }


# Backward-compat route: /signals/{symbol}
@APIRouter(prefix="/signals", tags=["signals_compat"]).get("/{symbol}")
async def get_signal_compat(symbol: str, with_ai: bool = False):
    out = await generate_signals([symbol.upper()], top_n=1, with_ai=with_ai)
    return out[0] if out else {"error": "no data", "symbol": symbol.upper()}


# ---------------------------------------------------------------------------
# Scan routes
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    mode: str = "manual"
    limit: int = 20
    top_n: int = 5
    with_ai: bool = False
    generate_charts: bool = True


@scan_router.post("")
async def trigger_scan(req: ScanRequest):
    """Trigger a full scanner run. Returns top signals."""
    from app.scanner import ScannerService
    from app.db import init_db
    await init_db()
    scanner = ScannerService(
        mode=req.mode,
        limit=req.limit,
        top_n=req.top_n,
        with_ai=req.with_ai,
        generate_charts=req.generate_charts,
    )
    result = await scanner.run()
    # strip private keys
    for sig in result.get("top_signals", []):
        sig.pop("_df", None)
        sig.pop("_snap", None)
        sig.pop("snapshot", None)
    return result


@scan_router.get("/latest")
async def get_latest_scans(limit: int = Query(10, ge=1, le=50)):
    """Return latest scan runs."""
    from sqlalchemy import select
    from app.db import async_session, ScanRun
    async with async_session() as db:
        result = await db.execute(
            select(ScanRun).order_by(ScanRun.id.desc()).limit(limit)
        )
        runs = result.scalars().all()
        return [
            {
                "id": r.id,
                "mode": r.mode,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "universe_count": r.universe_count,
                "scanned_count": r.scanned_count,
                "passed_count": r.passed_count,
                "failed_count": r.failed_count,
            }
            for r in runs
        ]


# ---------------------------------------------------------------------------
# Performance route
# ---------------------------------------------------------------------------

@APIRouter(prefix="/api/performance", tags=["performance"]).get("/summary")
async def performance_summary():
    """Return simple win/loss performance summary."""
    from sqlalchemy import func, select
    from app.db import async_session, Tracking
    async with async_session() as db:
        total = (await db.execute(select(func.count(Tracking.id)))).scalar() or 0
        avg_pnl = (await db.execute(select(func.avg(Tracking.pnl_pct)))).scalar() or 0.0
        wins = (
            await db.execute(select(func.count(Tracking.id)).where(Tracking.pnl_pct > 0))
        ).scalar() or 0
        tp1_hit = (
            await db.execute(
                select(func.count(Tracking.id)).where(Tracking.status == "TP1_HIT")
            )
        ).scalar() or 0
        tp2_hit = (
            await db.execute(
                select(func.count(Tracking.id)).where(Tracking.status == "TP2_HIT")
            )
        ).scalar() or 0
        sl_hit = (
            await db.execute(
                select(func.count(Tracking.id)).where(Tracking.status == "SL_HIT")
            )
        ).scalar() or 0
        win_rate = round(wins / total * 100.0, 1) if total else 0.0
        return {
            "total": total,
            "wins": wins,
            "win_rate_pct": win_rate,
            "avg_pnl_pct": round(float(avg_pnl), 2),
            "tp1_hit": tp1_hit,
            "tp2_hit": tp2_hit,
            "sl_hit": sl_hit,
        }


# ---------------------------------------------------------------------------
# Chart serving
# ---------------------------------------------------------------------------

@chart_router.get("/{filename}")
async def serve_chart(filename: str):
    """Serve chart PNG files."""
    from app.config import settings
    path = os.path.join(settings.CHART_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Chart not found")
    return FileResponse(path, media_type="image/png")
