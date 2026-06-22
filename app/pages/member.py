"""Member area — personal dashboard keyed by Telegram ID (MVP, no JWT)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>MAI-IDX-Signal — {title}</title>"
        "<script src='https://cdn.tailwindcss.com'></script></head>"
        "<body class='bg-gray-950 text-gray-100 p-6'>"
        "<nav class='mb-6 text-sm text-blue-400'>"
        "<a href='/' class='mr-4 hover:underline'>Home</a>"
        "<a href='/dashboard' class='mr-4 hover:underline'>Dashboard</a></nav>"
        f"<h1 class='text-2xl font-bold mb-4 text-white'>{title}</h1>{body}</body></html>"
    )


@router.get("/member", response_class=HTMLResponse)
async def member(tg_id: int = 0):
    if not tg_id:
        return HTMLResponse(_page(
            "Member Area",
            "<p class='text-gray-400'>Login via Telegram: kirim /subscribe ke bot, "
            "lalu buka <code>/member?tg_id=ID_ANDA</code>.</p>",
        ))

    from app.db import get_user_by_telegram_id, init_db, list_latest_signals
    from app.subscription.access import FREE_DAILY_LIMIT

    await init_db()
    user = await get_user_by_telegram_id(tg_id)
    if user is None:
        return HTMLResponse(_page(
            "Member Area",
            "<p class='text-red-400'>User tidak ditemukan. Kirim /subscribe ke bot dulu.</p>",
        ))

    limit = FREE_DAILY_LIMIT if user.tier == "free" else "∞"
    header = (
        "<div class='bg-gray-900 p-6 rounded-lg mb-6 max-w-xl'>"
        f"<p class='text-xl font-bold'>{user.full_name or user.username or tg_id}</p>"
        f"<p class='text-gray-400'>Tier: <span class='text-blue-400 font-semibold'>"
        f"{user.tier.upper()}</span></p>"
        f"<p class='text-gray-400'>Sinyal hari ini: {user.signal_count}/{limit}</p>"
        "</div>"
    )

    # Show recent platform signals (personal delivery history not yet tracked per-user)
    signals = await list_latest_signals(limit=20)
    if signals:
        wins = sum(1 for s in signals if (s.get("status") or "") in ("tp1", "tp2"))
        win_rate = wins / len(signals) * 100 if signals else 0.0
        cells = []
        for s in signals:
            cells.append(
                "<tr class='border-b border-gray-800'>"
                f"<td class='p-2 font-semibold'>{s['symbol']}</td>"
                f"<td class='p-2'>{s.get('action','HOLD')}</td>"
                f"<td class='p-2'>{s.get('entry',0):,.0f}</td>"
                f"<td class='p-2 text-xs text-gray-400'>{str(s.get('created_at',''))[:16]}</td>"
                "</tr>"
            )
        table = (
            f"<p class='text-sm text-gray-400 mb-2'>Win rate (20 sinyal terakhir): "
            f"{win_rate:.0f}%</p>"
            "<table class='w-full text-sm'><thead><tr class='text-left bg-gray-900 text-gray-400'>"
            "<th class='p-2'>Symbol</th><th class='p-2'>Action</th>"
            "<th class='p-2'>Entry</th><th class='p-2'>Waktu</th></tr></thead><tbody>"
            + "".join(cells) + "</tbody></table>"
        )
    else:
        table = "<p class='text-gray-400'>Belum ada sinyal.</p>"

    return HTMLResponse(_page("Member Area", header + table))
