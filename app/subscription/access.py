"""Access control for signal delivery by subscription tier."""
from __future__ import annotations

from typing import Tuple

FREE_DAILY_LIMIT = 2


async def can_receive_signal(telegram_id: int) -> Tuple[bool, str]:
    """Return (allowed, reason). Unknown users are allowed (auto-register)."""
    from app.db import get_user_by_telegram_id

    user = await get_user_by_telegram_id(telegram_id)
    if user is None:
        return True, ""  # new user, allow with auto-register
    if user.tier in ("pro", "admin"):
        return True, ""
    if (user.signal_count or 0) >= FREE_DAILY_LIMIT:
        return (
            False,
            f"Batas sinyal gratis {FREE_DAILY_LIMIT}/hari tercapai. "
            "Upgrade ke Pro untuk unlimited.",
        )
    return True, ""


async def get_or_create_user(telegram_id: int, tg_user=None):
    """Fetch a user, creating one from a Telegram user object if absent."""
    from app.db import create_user, get_user_by_telegram_id

    user = await get_user_by_telegram_id(telegram_id)
    if user is not None:
        return user
    username = getattr(tg_user, "username", "") or "" if tg_user else ""
    full_name = getattr(tg_user, "full_name", "") or "" if tg_user else ""
    await create_user(telegram_id, username=username, full_name=full_name)
    return await get_user_by_telegram_id(telegram_id)
