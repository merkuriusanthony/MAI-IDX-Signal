"""Signals + scan API routers."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.data.universe import load_universe
from app.signals.generator import generate_signals

signals_router = APIRouter(prefix="/signals", tags=["signals"])
scan_router = APIRouter(prefix="/scan", tags=["scan"])


@signals_router.get("/{symbol}")
async def get_signal(symbol: str, with_ai: bool = False):
    """Generate a single signal for ``symbol``."""
    out = await generate_signals([symbol.upper()], top_n=1, with_ai=with_ai)
    return out[0] if out else {"error": "no data", "symbol": symbol.upper()}


@scan_router.get("/")
async def scan(
    top_n: int = Query(5, ge=1, le=20),
    limit: int = Query(10, ge=1, le=200),
    with_ai: bool = False,
):
    """Scan the universe (first ``limit`` symbols) and return top signals."""
    universe = load_universe()[:limit]
    signals = await generate_signals(universe, top_n=top_n, with_ai=with_ai)
    return {"count": len(signals), "signals": signals}
