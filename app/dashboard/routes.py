"""HTML dashboard router."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Signal, Tracking, get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<script src='https://cdn.tailwindcss.com'></script></head>"
        "<body class='bg-gray-50 text-gray-800 p-6'>"
        f"<h1 class='text-2xl font-bold mb-4'>{title}</h1>{body}</body></html>"
    )


@router.get("/", response_class=HTMLResponse)
async def index(db: AsyncSession = Depends(get_session)):
    """List the latest signals."""
    result = await db.execute(
        select(Signal).order_by(Signal.created_at.desc()).limit(50)
    )
    rows = result.scalars().all()
    if not rows:
        return _page("Latest Signals", "<p>Belum ada sinyal.</p>")

    cells = []
    for s in rows:
        cells.append(
            "<tr class='border-b'>"
            f"<td class='p-2 font-semibold'>{s.symbol}</td>"
            f"<td class='p-2'>{s.label}</td>"
            f"<td class='p-2'>{s.score}</td>"
            f"<td class='p-2'>{s.entry}</td>"
            f"<td class='p-2'>{s.tp1}</td>"
            f"<td class='p-2'>{s.sl}</td>"
            f"<td class='p-2 text-xs text-gray-500'>{s.created_at}</td>"
            "</tr>"
        )
    table = (
        "<table class='w-full bg-white shadow rounded'>"
        "<thead><tr class='text-left bg-gray-100'>"
        "<th class='p-2'>Symbol</th><th class='p-2'>Label</th>"
        "<th class='p-2'>Score</th><th class='p-2'>Entry</th>"
        "<th class='p-2'>TP1</th><th class='p-2'>SL</th><th class='p-2'>Time</th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table>"
    )
    return _page("Latest Signals", table)


@router.get("/performance", response_class=HTMLResponse)
async def performance(db: AsyncSession = Depends(get_session)):
    """Aggregate tracking performance."""
    total = (await db.execute(select(func.count(Tracking.id)))).scalar() or 0
    avg_pnl = (await db.execute(select(func.avg(Tracking.pnl_pct)))).scalar() or 0.0
    wins = (
        await db.execute(
            select(func.count(Tracking.id)).where(Tracking.pnl_pct > 0)
        )
    ).scalar() or 0
    win_rate = (wins / total * 100.0) if total else 0.0

    body = (
        "<div class='grid grid-cols-3 gap-4'>"
        f"<div class='bg-white p-4 rounded shadow'><p class='text-gray-500'>Total Tracked</p>"
        f"<p class='text-3xl font-bold'>{total}</p></div>"
        f"<div class='bg-white p-4 rounded shadow'><p class='text-gray-500'>Avg PnL %</p>"
        f"<p class='text-3xl font-bold'>{avg_pnl:.2f}</p></div>"
        f"<div class='bg-white p-4 rounded shadow'><p class='text-gray-500'>Win Rate</p>"
        f"<p class='text-3xl font-bold'>{win_rate:.1f}%</p></div></div>"
    )
    return _page("Performance", body)


@router.get("/symbols/{ticker}", response_class=HTMLResponse)
async def symbol_detail(ticker: str, db: AsyncSession = Depends(get_session)):
    """Show signal history for one ticker."""
    ticker = ticker.upper()
    result = await db.execute(
        select(Signal)
        .where(Signal.symbol == ticker)
        .order_by(Signal.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    if not rows:
        return _page(f"{ticker}", "<p>Tidak ada riwayat sinyal.</p>")

    items = []
    for s in rows:
        try:
            reasons = json.loads(s.reasons) if s.reasons else []
        except json.JSONDecodeError:
            reasons = []
        items.append(
            "<div class='bg-white p-4 rounded shadow mb-3'>"
            f"<p class='font-bold'>{s.label} — score {s.score} "
            f"<span class='text-xs text-gray-400'>{s.created_at}</span></p>"
            f"<p>Entry {s.entry} | TP1 {s.tp1} | TP2 {s.tp2} | SL {s.sl}</p>"
            f"<ul class='list-disc ml-5 text-sm text-gray-600'>"
            + "".join(f"<li>{r}</li>" for r in reasons[:5])
            + "</ul></div>"
        )
    return _page(f"{ticker} History", "".join(items))
