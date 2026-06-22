"""Backtest API + dashboard routes."""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.backtest.engine import run_backtest, summarize
from app.data.fetch_yahoo import fetch_ohlcv
from app.data.universe import load_universe
from app.db import (
    create_backtest_run,
    fail_backtest_run,
    finish_backtest_run,
    get_backtest_results,
    get_backtest_run,
    list_backtest_runs,
    save_backtest_result,
    set_backtest_run_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backtest"])


def _period_for_days(days: int) -> str:
    """Map a day window to a yfinance period string."""
    if days <= 90:
        return "6mo"
    if days <= 180:
        return "1y"
    if days <= 365:
        return "2y"
    return "5y"


async def _execute_backtest(run_id: int, symbols: List[str], days: int) -> dict:
    """Fetch data, run the backtest over symbols, persist results for run_id.

    Drives the run through running -> completed/failed. Safe to call in the
    background; never raises (errors are recorded on the run row).
    """
    await set_backtest_run_status(run_id, "running")
    period = _period_for_days(days)
    all_results: List[dict] = []
    try:
        for sym in symbols:
            try:
                df = fetch_ohlcv(sym, period=period)
                if df is None or df.empty:
                    continue
                trades = run_backtest(sym, df)
                for t in trades:
                    t["score"] = float(t.get("score", 0.0))
                    await save_backtest_result(run_id, t)
                all_results.extend(trades)
            except Exception as exc:
                logger.warning("backtest error for %s: %s", sym, exc)
        summary = summarize(all_results)
        await finish_backtest_run(run_id, summary)
        return {"run_id": run_id, **summary}
    except Exception as exc:  # noqa: BLE001
        logger.exception("backtest run %s failed", run_id)
        await fail_backtest_run(run_id, str(exc))
        return {"run_id": run_id, "error": str(exc)}


async def _run_backtest_job(symbols: List[str], days: int) -> dict:
    """Synchronous (awaited) backtest — create run + execute inline.

    Kept for the dashboard button and any caller wanting the full result.
    """
    run_id = await create_backtest_run(
        strategy="default", universe_size=len(symbols)
    )
    return await _execute_backtest(run_id, symbols, days)


async def _queue_backtest_job(symbols: List[str], days: int) -> int:
    """Create a queued run and kick off execution in the background.

    Returns the run_id immediately so the HTTP request never blocks on the
    (potentially minutes-long) data fetch + simulation.
    """
    run_id = await create_backtest_run(
        strategy="default", universe_size=len(symbols), status="queued"
    )
    # Fire-and-forget; keep a reference so it is not GC'd mid-flight.
    task = asyncio.create_task(_execute_backtest(run_id, symbols, days))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return run_id


# Strong refs to in-flight background tasks (prevents premature GC).
_BACKGROUND_TASKS: set = set()


@router.post("/api/backtest")
async def trigger_backtest(payload: dict = Body(default=None)):
    """Queue a backtest run (non-blocking) on the given symbols.

    Default universe: top 50. Returns immediately with a queued run_id;
    poll GET /api/backtest/runs/{run_id} for progress and results.
    """
    from app.db import init_db

    await init_db()
    payload = payload or {}
    symbols: Optional[List[str]] = payload.get("symbols")
    days = int(payload.get("days", 90))
    if not symbols:
        symbols = load_universe()[:50]
    run_id = await _queue_backtest_job(symbols, days)
    return {
        "status": "queued",
        "run_id": run_id,
        "symbols": len(symbols),
        "days": days,
    }


@router.post("/api/backtest/run")
async def trigger_backtest_alias(payload: dict = Body(default=None)):
    """Alias of POST /api/backtest for dashboard/API consistency."""
    return await trigger_backtest(payload)


@router.get("/api/backtest/runs")
async def api_backtest_runs(limit: int = Query(20, ge=1, le=100)):
    """List latest backtest runs."""
    runs = await list_backtest_runs(limit=limit)
    return {"count": len(runs), "runs": runs}


@router.get("/api/backtest/runs/{run_id}")
async def api_backtest_run_detail(
    run_id: int, limit: int = Query(100, ge=1, le=1000)
):
    """Return a run's metadata plus a limited slice of its trade results."""
    run = await get_backtest_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    results = await get_backtest_results(run_id=run_id)
    return {"run": run, "result_count": len(results), "results": results[:limit]}


def _page(title: str, body: str) -> str:
    nav_links = (
        "<a href='/dashboard' class='mr-4 hover:underline'>Sinyal</a>"
        "<a href='/dashboard/performance' class='mr-4 hover:underline'>Performa</a>"
        "<a href='/dashboard/sectors' class='mr-4 hover:underline'>Sektor</a>"
        "<a href='/dashboard/scans' class='mr-4 hover:underline'>Scan Runs</a>"
        "<a href='/dashboard/backtest' class='mr-4 hover:underline'>Backtest</a>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>MAI-IDX-Signal — {title}</title>"
        "<script src='https://cdn.tailwindcss.com'></script></head>"
        "<body class='bg-gray-950 text-gray-100 p-6'>"
        f"<nav class='mb-6 text-sm text-blue-400'>{nav_links}</nav>"
        f"<h1 class='text-2xl font-bold mb-4 text-white'>{title}</h1>"
        f"{body}</body></html>"
    )


_OUTCOME_COLOR = {
    "tp1": "text-green-400", "tp2": "text-green-500",
    "sl": "text-red-400", "expired": "text-gray-400",
}


@router.get("/dashboard/backtest", response_class=HTMLResponse)
async def backtest_page():
    """Show results of the latest backtest run with summary cards.

    Resilient: never crashes if the backtest tables are missing or empty.
    """
    try:
        results = await get_backtest_results()
    except Exception as exc:  # noqa: BLE001 — table may not exist yet
        logger.warning("backtest_page: could not load results: %s", exc)
        results = []

    run_form = (
        "<form method='POST' action='/dashboard/backtest/run' class='mb-4 inline-block'>"
        "<button type='submit' class='bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm'>"
        "▶️ Jalankan Backtest (Top 50)</button></form>"
    )

    if not results:
        return _page("Backtest", run_form + "<p class='text-gray-400'>Belum ada hasil backtest.</p>")

    summary = summarize(results)
    cards = (
        "<div class='grid grid-cols-2 md:grid-cols-4 gap-4 mb-6'>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Total Trades</p>"
        f"<p class='text-2xl font-bold'>{summary['total_signals']}</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Win Rate</p>"
        f"<p class='text-2xl font-bold text-green-400'>{summary['win_rate']:.1f}%</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Avg Return</p>"
        f"<p class='text-2xl font-bold'>{summary['avg_return']:+.2f}%</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Max Drawdown</p>"
        f"<p class='text-2xl font-bold text-red-400'>{summary['max_drawdown']:+.2f}%</p></div>"
        "</div>"
    )

    cells = []
    for r in results:
        oc = r["outcome"]
        oc_color = _OUTCOME_COLOR.get(oc, "text-gray-300")
        pnl = r["pnl_pct"]
        pnl_color = "text-green-400" if pnl > 0 else "text-red-400" if pnl < 0 else "text-gray-400"
        cells.append(
            "<tr class='border-b border-gray-800 hover:bg-gray-900'>"
            f"<td class='p-2 font-semibold'>{r['symbol']}</td>"
            f"<td class='p-2 text-xs'>{r['entry_date']}</td>"
            f"<td class='p-2 text-xs'>{r['exit_date']}</td>"
            f"<td class='p-2'>{r['entry_price']:,.0f}</td>"
            f"<td class='p-2'>{r['exit_price']:,.0f}</td>"
            f"<td class='p-2 {pnl_color}'>{pnl:+.2f}%</td>"
            f"<td class='p-2 {oc_color} font-bold uppercase text-xs'>{oc}</td>"
            f"<td class='p-2 text-xs text-gray-400'>{r['sector']}</td>"
            "</tr>"
        )
    table = (
        "<div class='overflow-x-auto'><table class='w-full text-sm'>"
        "<thead><tr class='text-left bg-gray-900 text-gray-400'>"
        "<th class='p-2'>Symbol</th><th class='p-2'>Entry Date</th><th class='p-2'>Exit Date</th>"
        "<th class='p-2'>Entry</th><th class='p-2'>Exit</th><th class='p-2'>PnL</th>"
        "<th class='p-2'>Outcome</th><th class='p-2'>Sector</th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )
    return _page("Backtest", run_form + cards + table)


@router.post("/dashboard/backtest/run", response_class=HTMLResponse)
async def backtest_run_dashboard():
    """Run a backtest from the dashboard button, then redirect to results."""
    from fastapi.responses import RedirectResponse
    from app.db import init_db

    await init_db()
    symbols = load_universe()[:50]
    await _run_backtest_job(symbols, days=90)
    return RedirectResponse(url="/dashboard/backtest", status_code=303)
