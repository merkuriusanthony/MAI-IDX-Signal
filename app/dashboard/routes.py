"""HTML dashboard router."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Signal, ScanRun, Tracking, async_session, get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _page(title: str, body: str, nav: str = "") -> str:
    nav_links = nav or (
        "<a href='/dashboard' class='mr-4 hover:underline'>Sinyal</a>"
        "<a href='/dashboard/performance' class='mr-4 hover:underline'>Performa</a>"
        "<a href='/dashboard/scans' class='mr-4 hover:underline'>Scan Runs</a>"
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


ACTION_COLOR = {
    "BUY": "text-green-400",
    "WATCH": "text-yellow-400",
    "HOLD": "text-gray-400",
    "AVOID": "text-orange-400",
    "DANGER": "text-red-500",
}


@router.get("/", response_class=HTMLResponse)
async def index(db: AsyncSession = Depends(get_session)):
    """List the latest signals."""
    result = await db.execute(
        select(Signal).order_by(Signal.created_at.desc()).limit(50)
    )
    rows = result.scalars().all()
    if not rows:
        return _page("Latest Signals", "<p class='text-gray-400'>Belum ada sinyal.</p>")

    cells = []
    for s in rows:
        action = s.action or s.label
        color = ACTION_COLOR.get(action, "text-gray-300")
        cells.append(
            "<tr class='border-b border-gray-800 hover:bg-gray-900'>"
            f"<td class='p-2 font-semibold'><a href='/dashboard/symbols/{s.symbol}' class='text-blue-400 hover:underline'>{s.symbol}</a></td>"
            f"<td class='p-2 {color} font-bold'>{action}</td>"
            f"<td class='p-2'>{s.score:.1f}</td>"
            f"<td class='p-2'>{s.entry:,.0f}</td>"
            f"<td class='p-2'>{s.tp1:,.0f}</td>"
            f"<td class='p-2'>{s.tp2:,.0f}</td>"
            f"<td class='p-2 text-red-400'>{s.stop_loss or s.sl:,.0f}</td>"
            f"<td class='p-2 text-xs text-gray-500'>{str(s.created_at)[:16]}</td>"
            f"<td class='p-2 text-xs'><a href='/dashboard/signals/{s.id}' class='text-blue-400 hover:underline'>detail</a></td>"
            "</tr>"
        )
    table = (
        "<div class='overflow-x-auto'><table class='w-full text-sm'>"
        "<thead><tr class='text-left bg-gray-900 text-gray-400'>"
        "<th class='p-2'>Symbol</th><th class='p-2'>Action</th>"
        "<th class='p-2'>Score</th><th class='p-2'>Entry</th>"
        "<th class='p-2'>TP1</th><th class='p-2'>TP2</th><th class='p-2'>SL</th>"
        "<th class='p-2'>Waktu</th><th class='p-2'></th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )
    return _page("Latest Signals", table)


@router.get("/signals/{signal_id}", response_class=HTMLResponse)
async def signal_detail(signal_id: int, db: AsyncSession = Depends(get_session)):
    """Show detail for one signal."""
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    s = result.scalar_one_or_none()
    if not s:
        return _page("Not Found", "<p class='text-red-400'>Sinyal tidak ditemukan.</p>")

    try:
        reasons = json.loads(s.reasons) if s.reasons else []
    except Exception:
        reasons = []

    action = s.action or s.label
    color = ACTION_COLOR.get(action, "text-gray-300")
    chart_html = ""
    if s.chart_path:
        fname = s.chart_path.split("/")[-1]
        chart_html = f"<img src='/charts/{fname}' class='mt-4 rounded max-w-full' />"

    reason_html = "".join(f"<li class='text-sm text-gray-300'>• {r}</li>" for r in reasons)
    body = (
        f"<div class='bg-gray-900 p-6 rounded-lg max-w-2xl'>"
        f"<h2 class='text-xl font-bold {color}'>{s.symbol} — {action}</h2>"
        f"<p class='text-gray-400 text-sm mb-4'>{str(s.created_at)[:19]}</p>"
        f"<div class='grid grid-cols-2 gap-4 mb-4'>"
        f"<div><p class='text-gray-500 text-xs'>Score</p><p class='text-xl font-bold'>{s.score:.1f}/100</p></div>"
        f"<div><p class='text-gray-500 text-xs'>Confidence</p><p class='text-xl font-bold'>{int(s.confidence*100)}%</p></div>"
        f"<div><p class='text-gray-500 text-xs'>Entry</p><p class='text-lg font-semibold'>{s.entry:,.0f}</p></div>"
        f"<div><p class='text-gray-500 text-xs'>TP1 / TP2</p><p class='text-lg font-semibold'>{s.tp1:,.0f} / {s.tp2:,.0f}</p></div>"
        f"<div><p class='text-gray-500 text-xs'>Stop Loss</p><p class='text-lg font-semibold text-red-400'>{s.stop_loss or s.sl:,.0f}</p></div>"
        f"<div><p class='text-gray-500 text-xs'>Status</p><p class='text-lg font-semibold'>{s.status}</p></div>"
        f"</div>"
        f"<ul class='mb-4'>{reason_html}</ul>"
        + (f"<p class='text-sm text-gray-400 italic'>{s.summary}</p>" if s.summary else "")
        + chart_html
        + "</div>"
    )
    return _page(f"{s.symbol} Signal #{signal_id}", body)


@router.get("/performance", response_class=HTMLResponse)
async def performance(db: AsyncSession = Depends(get_session)):
    """Aggregate tracking performance."""
    total = (await db.execute(select(func.count(Tracking.id)))).scalar() or 0
    avg_pnl = (await db.execute(select(func.avg(Tracking.pnl_pct)))).scalar() or 0.0
    wins = (
        await db.execute(select(func.count(Tracking.id)).where(Tracking.pnl_pct > 0))
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

    def card(label: str, val: str) -> str:
        return (
            f"<div class='bg-gray-900 p-4 rounded-lg shadow'>"
            f"<p class='text-gray-500 text-sm'>{label}</p>"
            f"<p class='text-3xl font-bold text-white'>{val}</p></div>"
        )

    body = (
        "<div class='grid grid-cols-2 md:grid-cols-4 gap-4'>"
        + card("Total Tracked", str(total))
        + card("Win Rate", f"{win_rate:.1f}%")
        + card("Avg PnL %", f"{float(avg_pnl):.2f}%")
        + card("TP1/TP2/SL", f"{tp1_hit}/{tp2_hit}/{sl_hit}")
        + "</div>"
    )
    return _page("Performance", body)


@router.get("/scans", response_class=HTMLResponse)
async def scans_list(db: AsyncSession = Depends(get_session)):
    """Show recent scan runs."""
    result = await db.execute(
        select(ScanRun).order_by(ScanRun.id.desc()).limit(20)
    )
    runs = result.scalars().all()
    if not runs:
        return _page("Scan Runs", "<p class='text-gray-400'>Belum ada scan run.</p>")

    status_color = {"success": "text-green-400", "failed": "text-red-400",
                    "running": "text-yellow-400", "partial": "text-orange-400"}
    cells = []
    for r in runs:
        sc = status_color.get(r.status, "text-gray-300")
        cells.append(
            f"<tr class='border-b border-gray-800'>"
            f"<td class='p-2'>{r.id}</td>"
            f"<td class='p-2'>{r.mode}</td>"
            f"<td class='p-2 {sc} font-semibold'>{r.status}</td>"
            f"<td class='p-2'>{r.universe_count}</td>"
            f"<td class='p-2'>{r.scanned_count}</td>"
            f"<td class='p-2 text-green-400'>{r.passed_count}</td>"
            f"<td class='p-2 text-red-400'>{r.failed_count}</td>"
            f"<td class='p-2 text-xs text-gray-500'>{(r.started_at or '')[:16]}</td>"
            "</tr>"
        )
    table = (
        "<div class='overflow-x-auto'><table class='w-full text-sm'>"
        "<thead><tr class='text-left bg-gray-900 text-gray-400'>"
        "<th class='p-2'>ID</th><th class='p-2'>Mode</th><th class='p-2'>Status</th>"
        "<th class='p-2'>Universe</th><th class='p-2'>Scanned</th>"
        "<th class='p-2'>Passed</th><th class='p-2'>Failed</th><th class='p-2'>Waktu</th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )
    return _page("Scan Runs", table)


@router.get("/symbols/{ticker}", response_class=HTMLResponse)
async def symbol_detail(ticker: str, db: AsyncSession = Depends(get_session)):
    """Show signal history for one ticker."""
    ticker = ticker.upper()
    result = await db.execute(
        select(Signal).where(Signal.symbol == ticker).order_by(Signal.created_at.desc()).limit(50)
    )
    rows = result.scalars().all()
    if not rows:
        return _page(f"{ticker}", "<p class='text-gray-400'>Tidak ada riwayat sinyal.</p>")

    items = []
    for s in rows:
        try:
            reasons = json.loads(s.reasons) if s.reasons else []
        except json.JSONDecodeError:
            reasons = []
        action = s.action or s.label
        color = ACTION_COLOR.get(action, "text-gray-300")
        items.append(
            "<div class='bg-gray-900 p-4 rounded-lg mb-3'>"
            f"<p class='font-bold {color}'>{action} — score {s.score:.1f} "
            f"<span class='text-xs text-gray-500'>{str(s.created_at)[:16]}</span></p>"
            f"<p class='text-sm'>Entry {s.entry:,.0f} | TP1 {s.tp1:,.0f} | TP2 {s.tp2:,.0f} | SL {s.stop_loss or s.sl:,.0f}</p>"
            f"<ul class='list-disc ml-5 text-sm text-gray-400'>"
            + "".join(f"<li>{r}</li>" for r in reasons[:5])
            + "</ul></div>"
        )
    return _page(f"{ticker} History", "".join(items))
