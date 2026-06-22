"""Admin panel — key-auth via ADMIN_KEY env var (MVP)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import settings

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


def _authorized(key: str) -> bool:
    expected = settings.effective_admin_key()
    return bool(key) and key == expected


@router.get("/admin", response_class=HTMLResponse)
async def admin(key: str = ""):
    if not _authorized(key):
        return HTMLResponse(
            _page("Admin", "<p class='text-red-400'>⛔ Akses ditolak. Sertakan ?key=ADMIN_KEY.</p>"),
            status_code=403,
        )

    from app.db import init_db, list_users

    await init_db()
    users = await list_users(limit=200)

    if users:
        cells = []
        for u in users:
            grant_url = f"/admin/grant?key={key}&tg_id={u['telegram_id']}&tier=pro"
            cells.append(
                "<tr class='border-b border-gray-800'>"
                f"<td class='p-2'>{u['telegram_id']}</td>"
                f"<td class='p-2'>{u['full_name'] or u['username']}</td>"
                f"<td class='p-2 font-semibold'>{u['tier'].upper()}</td>"
                f"<td class='p-2'>{u['signal_count']}</td>"
                f"<td class='p-2 text-xs'><a href='{grant_url}' class='text-blue-400 hover:underline'>grant pro</a></td>"
                "</tr>"
            )
        table = (
            "<table class='w-full text-sm'><thead><tr class='text-left bg-gray-900 text-gray-400'>"
            "<th class='p-2'>Telegram ID</th><th class='p-2'>Nama</th>"
            "<th class='p-2'>Tier</th><th class='p-2'>Sinyal</th><th class='p-2'></th>"
            "</tr></thead><tbody>" + "".join(cells) + "</tbody></table>"
        )
    else:
        table = "<p class='text-gray-400'>Belum ada user.</p>"

    return HTMLResponse(_page("Admin Panel", table))


@router.get("/admin/grant", response_class=HTMLResponse)
async def admin_grant(key: str = "", tg_id: int = 0, tier: str = "pro"):
    if not _authorized(key):
        return HTMLResponse(
            _page("Admin", "<p class='text-red-400'>⛔ Akses ditolak.</p>"), status_code=403
        )

    from fastapi.responses import RedirectResponse
    from app.db import create_user, init_db, set_user_tier

    await init_db()
    if tg_id:
        ok = await set_user_tier(tg_id, tier)
        if not ok:
            await create_user(tg_id, tier=tier)
    return RedirectResponse(url=f"/admin?key={key}", status_code=303)
