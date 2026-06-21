"""IDX universe loader."""
from __future__ import annotations

import os
from typing import List

from app.config import settings

FALLBACK_UNIVERSE: List[str] = ["BBCA", "BBRI", "TLKM", "ASII", "BMRI"]


def load_universe(path: str | None = None) -> List[str]:
    """Load the IDX ticker universe from a text file (one symbol per line).

    Falls back to a small blue-chip list if the file is missing or empty.
    """
    path = path or settings.IDX_UNIVERSE_PATH
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                symbols = [
                    line.strip().upper()
                    for line in fh
                    if line.strip() and not line.strip().startswith("#")
                ]
            if symbols:
                return symbols
        except OSError:
            pass
    return list(FALLBACK_UNIVERSE)
