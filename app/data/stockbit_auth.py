"""Stockbit auth helper — single token source for fetch_stockbit.

Mirrors the file-read + cookie-fallback logic proven in
``app/data/universe_update.py:_stockbit_token``. No network, no refresh
(the host token manager owns daily refresh and writes the JWT file).
"""
from __future__ import annotations

import logging
import os
from typing import Dict

from app.config import settings

logger = logging.getLogger(__name__)


def get_token() -> str:
    """Resolve a Stockbit access JWT.

    Priority:
      1. File at settings.STOCKBIT_ACCESS_FILE (host-refreshed daily).
      2. settings.STOCKBIT_SESSION_COOKIE env (raw bearer or "Bearer ...").

    Returns "" if neither yields a token. Never raises.
    """
    try:
        path = (settings.STOCKBIT_ACCESS_FILE or "").strip()
        if path and os.path.exists(path):
            try:
                tok = open(path, "r", encoding="utf-8").read().strip()
                if tok:
                    return tok[7:].strip() if tok.lower().startswith("bearer ") else tok
            except Exception as exc:
                logger.debug("stockbit access file read failed: %s", exc)
        cookie = (settings.STOCKBIT_SESSION_COOKIE or "").strip()
        if cookie:
            return cookie[7:].strip() if cookie.lower().startswith("bearer ") else cookie
    except Exception as exc:
        logger.debug("get_token error: %s", exc)
    return ""


def auth_headers(token: str) -> Dict[str, str]:
    """Standard browser-like headers for Stockbit exodus API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }
