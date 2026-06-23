"""HTML dashboard router."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.sectors import get_profile, get_sector
from app.db import Signal, ScanRun, Tracking, async_session, get_session, _utcnow

BOARD_COLOR = {"RG": "text-blue-400", "NG": "text-orange-400", "TN": "text-yellow-400"}

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _page(title: str, body: str, nav: str = "") -> str:
    nav_links = nav or (
        "<a href='/dashboard' class='mr-4 hover:underline'>Sinyal</a>"
        "<a href='/dashboard/performance' class='mr-4 hover:underline'>Performa</a>"
        "<a href='/dashboard/sectors' class='mr-4 hover:underline'>Sektor</a>"
        "<a href='/dashboard/scans' class='mr-4 hover:underline'>Scan Runs</a>"
        "<a href='/dashboard/backtest' class='mr-4 hover:underline'>Backtest</a>"
        "<a href='/dashboard/status' class='mr-4 hover:underline'>Status</a>"
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


def _bar(label: str, pct: float, color: str = "bg-green-500") -> str:
    """A simple CSS width-% horizontal bar."""
    return (
        f"<div class='mb-2'><span class='text-sm text-gray-400 w-32 inline-block'>{label}</span>"
        f"<div class='inline-block bg-gray-800 w-48 h-4 rounded align-middle'>"
        f"<div class='{color} h-4 rounded' style='width:{min(pct, 100):.0f}%'></div></div>"
        f"<span class='text-sm ml-2'>{pct:.1f}%</span></div>"
    )


_CLOSED_STATUSES = {"tp1", "tp2", "stopped", "expired"}
_STATUS_LABEL = {
    "tp1": ("TP1", "text-green-400"), "tp2": ("TP2", "text-green-500"),
    "stopped": ("SL", "text-red-400"), "expired": ("EXPIRED", "text-gray-400"),
}


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

    scan_form = (
        "<form method='POST' action='/dashboard/scan' class='mb-4 inline-flex items-center gap-2' "
        "onsubmit=\"this.querySelector('button').disabled=true;"
        "this.querySelector('button').textContent='⏳ Memulai scan…';\">"
        "<input type='hidden' name='mode' value='manual'>"
        "<select name='limit' class='bg-gray-800 text-white text-sm rounded px-2 py-2'>"
        "<option value='20'>Top 20 (cepat)</option>"
        "<option value='100'>Top 100</option>"
        "<option value='0'>Full universe (semua emiten)</option>"
        "</select>"
        "<button type='submit' class='bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm'>"
        "🔍 Scan Sekarang</button>"
        "<span id='signal-count' class='text-xs text-gray-500 ml-2'></span>"
        "</form>"
        "<script>"
        "async function refreshSignals(){try{"
        "const r=await fetch('/api/signals/latest?limit=20');const d=await r.json();"
        "document.getElementById('signal-count').textContent=(d.count||0)+' sinyal';"
        "}catch(e){}}setInterval(refreshSignals,60000);refreshSignals();"
        "</script>"
    )

    if not rows:
        return _page("Latest Signals", scan_form + "<p class='text-gray-400'>Belum ada sinyal.</p>")

    cells = []
    for s in rows:
        action = s.action or s.label
        color = ACTION_COLOR.get(action, "text-gray-300")
        board = get_profile(s.symbol).get("board", "RG")
        board_color = BOARD_COLOR.get(board, "text-gray-400")
        sl_val = s.stop_loss or s.sl
        try:
            ts = int(s.created_at.timestamp())
        except Exception:
            try:
                from datetime import datetime as _dt
                ts = int(_dt.fromisoformat(str(s.created_at)).timestamp())
            except Exception:
                ts = 0
        cells.append(
            "<tr class='border-b border-gray-800 hover:bg-gray-900' "
            f"data-symbol='{s.symbol}' data-action='{action}' data-board='{board}' "
            f"data-score='{s.score}' data-entry='{s.entry}' data-tp1='{s.tp1}' "
            f"data-tp2='{s.tp2}' data-sl='{sl_val}' data-ts='{ts}'>"
            f"<td class='p-2 font-semibold'><a href='/dashboard/symbols/{s.symbol}' class='text-blue-400 hover:underline'>{s.symbol}</a></td>"
            f"<td class='p-2 {board_color} text-xs font-bold'>{board}</td>"
            f"<td class='p-2 {color} font-bold'>{action}</td>"
            f"<td class='p-2'>{s.score:.1f}</td>"
            f"<td class='p-2'>{s.entry:,.0f}</td>"
            f"<td class='p-2'>{s.tp1:,.0f}</td>"
            f"<td class='p-2'>{s.tp2:,.0f}</td>"
            f"<td class='p-2 text-red-400'>{sl_val:,.0f}</td>"
            f"<td class='p-2 text-xs text-gray-500'>{str(s.created_at)[:16]}</td>"
            f"<td class='p-2 text-xs'><a href='/dashboard/signals/{s.id}' class='text-blue-400 hover:underline'>detail</a></td>"
            "</tr>"
        )

    # client-side search / filter / sort controls
    controls = (
        "<div class='mb-3 flex flex-wrap items-center gap-2'>"
        "<div class='relative'>"
        "<input id='sig-search' type='text' placeholder='Cari emiten…' "
        "class='bg-gray-800 text-white text-sm rounded px-3 py-2 w-44 pr-7' "
        "oninput='sigFilter()'>"
        "<button id='sig-clear' type='button' onclick='sigClear()' "
        "class='absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white text-sm hidden'>×</button>"
        "</div>"
        "<select id='sig-action' onchange='sigFilter()' class='bg-gray-800 text-white text-sm rounded px-2 py-2'>"
        "<option value=''>Semua action</option>"
        "<option value='BUY'>BUY</option><option value='WATCH'>WATCH</option>"
        "<option value='AVOID'>AVOID</option><option value='DANGER'>DANGER</option>"
        "</select>"
        "<select id='sig-board' onchange='sigFilter()' class='bg-gray-800 text-white text-sm rounded px-2 py-2'>"
        "<option value=''>Semua board</option>"
        "<option value='RG'>RG</option><option value='NG'>NG</option><option value='TN'>TN</option>"
        "</select>"
        "<span id='sig-counter' class='text-xs text-gray-500 ml-1'></span>"
        "</div>"
    )

    headers = [
        ("Symbol", "symbol", "str"),
        ("Board", "board", "str"),
        ("Action", "action", "str"),
        ("Score", "score", "num"),
        ("Entry", "entry", "num"),
        ("TP1", "tp1", "num"),
        ("TP2", "tp2", "num"),
        ("SL", "sl", "num"),
        ("Waktu", "ts", "num"),
    ]
    head_cells = "".join(
        f"<th class='p-2 cursor-pointer select-none hover:text-white' "
        f"data-key='{key}' data-type='{typ}' onclick=\"sigSort('{key}','{typ}')\">"
        f"{label}<span class='sort-arrow'></span></th>"
        for label, key, typ in headers
    )
    table = (
        "<div class='overflow-x-auto'><table id='signal-table' class='w-full text-sm'>"
        "<thead><tr class='text-left bg-gray-900 text-gray-400'>"
        + head_cells
        + "<th class='p-2'></th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )

    sig_js = (
        "<script>"
        "(function(){"
        "var tbody=document.querySelector('#signal-table tbody');"
        "var rows=Array.prototype.slice.call(tbody.querySelectorAll('tr'));"
        "var total=rows.length;var sortKey=null,sortDir=1;"
        "window.sigFilter=function(){"
        "var q=(document.getElementById('sig-search').value||'').trim().toUpperCase();"
        "var a=document.getElementById('sig-action').value;"
        "var b=document.getElementById('sig-board').value;"
        "document.getElementById('sig-clear').classList.toggle('hidden',!q);"
        "var shown=0;"
        "rows.forEach(function(r){"
        "var ok=(!q||r.getAttribute('data-symbol').toUpperCase().indexOf(q)>=0)"
        "&&(!a||r.getAttribute('data-action')===a)"
        "&&(!b||r.getAttribute('data-board')===b);"
        "r.style.display=ok?'':'none';if(ok)shown++;});"
        "document.getElementById('sig-counter').textContent='Menampilkan '+shown+' dari '+total+' sinyal';"
        "};"
        "window.sigClear=function(){"
        "document.getElementById('sig-search').value='';sigFilter();};"
        "window.sigSort=function(key,type){"
        "if(sortKey===key){sortDir=-sortDir;}else{sortKey=key;sortDir=1;}"
        "rows.sort(function(x,y){"
        "var vx=x.getAttribute('data-'+key),vy=y.getAttribute('data-'+key);"
        "if(type==='num'){vx=parseFloat(vx)||0;vy=parseFloat(vy)||0;return (vx-vy)*sortDir;}"
        "return vx.localeCompare(vy)*sortDir;});"
        "rows.forEach(function(r){tbody.appendChild(r);});"
        "document.querySelectorAll('#signal-table th .sort-arrow').forEach(function(s){s.textContent='';});"
        "var th=document.querySelector(\"#signal-table th[data-key='\"+key+\"']\");"
        "if(th)th.querySelector('.sort-arrow').textContent=sortDir>0?' \\u25B2':' \\u25BC';"
        "};"
        "sigFilter();"
        "})();"
        "</script>"
    )
    return _page("Latest Signals", scan_form + controls + table + sig_js)


@router.post("/scan", response_class=HTMLResponse)
async def trigger_scan_dashboard(mode: str = Form("manual"), limit: int = Form(20)):
    """Kick off a scan in the BACKGROUND, then redirect to the live scan list.

    The scan runs async so the browser never blocks — full-universe scans
    (959 emiten) can take minutes. /dashboard/scans auto-refreshes and shows
    live progress (status running -> success, scanned counter).
    """
    import asyncio

    from app.db import init_db
    from app.scanner import ScannerService

    await init_db()
    # limit=0 (or falsy) => full universe; otherwise cap to top N.
    eff_limit = limit if limit and limit > 0 else None

    async def _run() -> None:
        try:
            scanner = ScannerService(
                mode="manual", limit=eff_limit, top_n=5, generate_charts=True
            )
            await scanner.run()
        except Exception:  # never let a bg task die silently un-logged
            import logging
            logging.getLogger("app.scanner").exception("dashboard bg scan failed")

    asyncio.create_task(_run())
    return RedirectResponse(url="/dashboard/scans", status_code=303)


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
    board = get_profile(s.symbol).get("board", "RG")
    board_color = BOARD_COLOR.get(board, "text-gray-400")
    chart_html = ""
    if s.chart_path:
        fname = s.chart_path.split("/")[-1]
        chart_html = f"<img src='/charts/{fname}' class='mt-4 rounded max-w-full' />"

    reason_html = "".join(f"<li class='text-sm text-gray-300'>• {r}</li>" for r in reasons)
    body = (
        f"<div class='bg-gray-900 p-6 rounded-lg max-w-2xl'>"
        f"<h2 class='text-xl font-bold {color}'>{s.symbol} — {action} "
        f"<span class='{board_color} text-sm'>[{board}]</span></h2>"
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

    cards = (
        "<div class='grid grid-cols-2 md:grid-cols-4 gap-4 mb-6'>"
        + card("Total Tracked", str(total))
        + card("Win Rate", f"{win_rate:.1f}%")
        + card("Avg PnL %", f"{float(avg_pnl):.2f}%")
        + card("TP1/TP2/SL", f"{tp1_hit}/{tp2_hit}/{sl_hit}")
        + "</div>"
    )

    # win-rate bars
    closed = tp1_hit + tp2_hit + sl_hit
    tp_pct = (tp1_hit + tp2_hit) / closed * 100 if closed else 0.0
    sl_pct = sl_hit / closed * 100 if closed else 0.0
    bars = (
        "<div class='bg-gray-900 p-4 rounded-lg mb-6'>"
        "<h2 class='text-lg font-semibold mb-3'>Hit Rate</h2>"
        + _bar("Win Rate", win_rate, "bg-green-500")
        + _bar("TP hit", tp_pct, "bg-green-600")
        + _bar("SL hit", sl_pct, "bg-red-500")
        + "</div>"
    )

    # recent closed signals
    closed_res = await db.execute(
        select(Signal)
        .where(Signal.status.in_(list(_CLOSED_STATUSES)))
        .order_by(Signal.created_at.desc())
        .limit(10)
    )
    closed_rows = closed_res.scalars().all()
    track_res = await db.execute(select(Tracking))
    track_by_sig = {t.signal_id: t for t in track_res.scalars().all()}

    closed_cells = []
    sector_stats: dict = {}
    for s in closed_rows:
        t = track_by_sig.get(s.id)
        exit_price = t.current_price if t else s.entry
        pnl = t.pnl_pct if t else 0.0
        holding = (_utcnow() - s.created_at).days if s.created_at else 0
        label, lcolor = _STATUS_LABEL.get(s.status, (s.status, "text-gray-400"))
        pnl_color = "text-green-400" if pnl > 0 else "text-red-400" if pnl < 0 else "text-gray-400"
        closed_cells.append(
            "<tr class='border-b border-gray-800'>"
            f"<td class='p-2 font-semibold'>{s.symbol}</td>"
            f"<td class='p-2'>{s.action or s.label}</td>"
            f"<td class='p-2'>{s.entry:,.0f}</td>"
            f"<td class='p-2'>{exit_price:,.0f}</td>"
            f"<td class='p-2 {pnl_color}'>{pnl:+.1f}%</td>"
            f"<td class='p-2'>{holding}d</td>"
            f"<td class='p-2 {lcolor} font-semibold'>{label}</td>"
            "</tr>"
        )

    closed_table = (
        "<div class='bg-gray-900 p-4 rounded-lg mb-6'>"
        "<h2 class='text-lg font-semibold mb-3'>Sinyal Closed Terbaru</h2>"
        "<div class='overflow-x-auto'><table class='w-full text-sm'>"
        "<thead><tr class='text-left text-gray-400'>"
        "<th class='p-2'>Symbol</th><th class='p-2'>Action</th><th class='p-2'>Entry</th>"
        "<th class='p-2'>Exit</th><th class='p-2'>PnL</th><th class='p-2'>Hold</th>"
        "<th class='p-2'>Status</th></tr></thead><tbody>"
        + ("".join(closed_cells) or "<tr><td class='p-2 text-gray-500' colspan='7'>Belum ada.</td></tr>")
        + "</tbody></table></div></div>"
    )

    # top-3 sectors by win rate (last 7 days signals)
    from datetime import timedelta
    cutoff = _utcnow() - timedelta(days=7)
    recent_res = await db.execute(select(Signal).where(Signal.created_at >= cutoff))
    for s in recent_res.scalars().all():
        sec = get_sector(s.symbol)
        st = sector_stats.setdefault(sec, {"wins": 0, "total": 0})
        st["total"] += 1
        if s.status in {"tp1", "tp2"}:
            st["wins"] += 1
    sector_bars = []
    ranked = sorted(
        sector_stats.items(),
        key=lambda kv: (kv[1]["wins"] / kv[1]["total"] if kv[1]["total"] else 0),
        reverse=True,
    )[:3]
    for sec, st in ranked:
        wr = st["wins"] / st["total"] * 100 if st["total"] else 0.0
        sector_bars.append(_bar(f"{sec} ({st['total']})", wr, "bg-blue-500"))
    sector_block = (
        "<div class='bg-gray-900 p-4 rounded-lg'>"
        "<h2 class='text-lg font-semibold mb-3'>Top Sektor (7 hari)</h2>"
        + ("".join(sector_bars) or "<p class='text-gray-500 text-sm'>Belum ada data.</p>")
        + "</div>"
    )

    return _page("Performance", cards + bars + closed_table + sector_block)


@router.get("/sectors", response_class=HTMLResponse)
async def sectors(db: AsyncSession = Depends(get_session)):
    """Rank IDX sectors by avg signal score over the last 7 days."""
    from datetime import timedelta

    cutoff = _utcnow() - timedelta(days=7)
    result = await db.execute(select(Signal).where(Signal.created_at >= cutoff))
    rows = result.scalars().all()
    if not rows:
        return _page("Sektor", "<p class='text-gray-400'>Belum ada sinyal 7 hari terakhir.</p>")

    stats: dict = {}
    for s in rows:
        sec = get_sector(s.symbol)
        st = stats.setdefault(sec, {"sum": 0.0, "count": 0, "top_symbol": "", "top_score": -1.0})
        st["sum"] += s.score
        st["count"] += 1
        if s.score > st["top_score"]:
            st["top_score"] = s.score
            st["top_symbol"] = s.symbol

    ranked = sorted(
        stats.items(),
        key=lambda kv: kv[1]["sum"] / kv[1]["count"],
        reverse=True,
    )
    cells = []
    for sec, st in ranked:
        avg = st["sum"] / st["count"]
        cells.append(
            "<tr class='border-b border-gray-800'>"
            f"<td class='p-2 font-semibold'>{sec}</td>"
            f"<td class='p-2'>{avg:.1f}</td>"
            f"<td class='p-2'>{st['count']}</td>"
            f"<td class='p-2 text-blue-400'>{st['top_symbol']}</td>"
            "</tr>"
        )
    table = (
        "<div class='overflow-x-auto'><table class='w-full text-sm'>"
        "<thead><tr class='text-left bg-gray-900 text-gray-400'>"
        "<th class='p-2'>Sektor</th><th class='p-2'>Avg Score</th>"
        "<th class='p-2'>Jumlah Sinyal</th><th class='p-2'>Top Symbol</th>"
        "</tr></thead><tbody>" + "".join(cells) + "</tbody></table></div>"
    )
    return _page("Ranking Sektor (7 hari)", table)


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
    # Auto-refresh while any run is still 'running' so progress shows live.
    any_running = any(r.status == "running" for r in runs)
    refresh = (
        "<p class='text-yellow-400 text-xs mb-2'>⏳ Scan berjalan… halaman refresh otomatis.</p>"
        "<script>setTimeout(()=>location.reload(),4000);</script>"
        if any_running else ""
    )
    return _page("Scan Runs", refresh + table)


@router.get("/status", response_class=HTMLResponse)
async def status_page():
    """Ops page: app version, DB status, table status, latest scan/signals,
    plus quick links to the rest of the app."""
    from app.db import get_db_status
    from app.main import VERSION

    db = await get_db_status()
    conn = db.get("connected")
    conn_color = "text-green-400" if conn else "text-red-400"

    cards = (
        "<div class='grid grid-cols-2 md:grid-cols-4 gap-4 mb-6'>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Versi</p>"
        f"<p class='text-2xl font-bold'>{VERSION}</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Database</p>"
        f"<p class='text-2xl font-bold {conn_color}'>{'OK' if conn else 'DOWN'}</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Total Sinyal</p>"
        f"<p class='text-2xl font-bold'>{db.get('signal_count', 0)}</p></div>"
        f"<div class='bg-gray-900 p-4 rounded'><p class='text-xs text-gray-500'>Sinyal Terbaru</p>"
        f"<p class='text-sm font-semibold'>{(db.get('latest_signal_at') or '-')[:19]}</p></div>"
        "</div>"
    )

    table_rows = "".join(
        f"<tr class='border-b border-gray-800'><td class='p-2'>{name}</td>"
        f"<td class='p-2 {'text-green-400' if present else 'text-red-400'} font-semibold'>"
        f"{'ada' if present else 'tidak ada'}</td></tr>"
        for name, present in (db.get("tables") or {}).items()
    )
    tables_block = (
        "<div class='bg-gray-900 p-4 rounded-lg mb-6'>"
        "<h2 class='text-lg font-semibold mb-3'>Tabel Database</h2>"
        "<table class='w-full text-sm'><thead><tr class='text-left text-gray-400'>"
        "<th class='p-2'>Tabel</th><th class='p-2'>Status</th></tr></thead><tbody>"
        + (table_rows or "<tr><td class='p-2 text-gray-500' colspan='2'>-</td></tr>")
        + "</tbody></table></div>"
    )

    scan = db.get("latest_scan")
    if scan:
        scan_block = (
            "<div class='bg-gray-900 p-4 rounded-lg mb-6'>"
            "<h2 class='text-lg font-semibold mb-3'>Scan Terakhir</h2>"
            f"<p class='text-sm text-gray-300'>#{scan['id']} · {scan['mode']} · "
            f"<span class='font-semibold'>{scan['status']}</span> · "
            f"passed {scan['passed_count']}/{scan['scanned_count']} · "
            f"{(scan.get('started_at') or '')[:19]}</p></div>"
        )
    else:
        scan_block = (
            "<div class='bg-gray-900 p-4 rounded-lg mb-6'>"
            "<h2 class='text-lg font-semibold mb-3'>Scan Terakhir</h2>"
            "<p class='text-sm text-gray-500'>Belum ada scan.</p></div>"
        )

    err_block = (
        f"<div class='bg-red-900/40 p-4 rounded-lg mb-6'><p class='text-sm text-red-300'>"
        f"Error: {db['error']}</p></div>"
        if db.get("error")
        else ""
    )

    links = (
        "<div class='bg-gray-900 p-4 rounded-lg'>"
        "<h2 class='text-lg font-semibold mb-3'>Tautan</h2>"
        "<div class='flex flex-wrap gap-3 text-sm text-blue-400'>"
        "<a href='/dashboard' class='hover:underline'>Dashboard</a>"
        "<a href='/dashboard/performance' class='hover:underline'>Performa</a>"
        "<a href='/dashboard/sectors' class='hover:underline'>Sektor</a>"
        "<a href='/dashboard/backtest' class='hover:underline'>Backtest</a>"
        "<a href='/admin' class='hover:underline'>Admin</a>"
        "<a href='/member' class='hover:underline'>Member</a>"
        "<a href='/api/status' class='hover:underline'>/api/status (JSON)</a>"
        "</div></div>"
    )

    return _page("Status", cards + err_block + tables_block + scan_block + links)


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
