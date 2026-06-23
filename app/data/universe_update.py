"""Daily IDX universe auto-update (IPO / delisting sync).

Fetches the current authoritative list of IDX-listed tickers via a 3-tier
fallback (IDX official -> Stockbit -> Yahoo Finance), diffs it against the
on-disk universe file, and atomically rewrites the file when the change passes
a sanity gate. Designed to be called from a daily scheduler job; the scan
universe loader (``load_universe``) re-reads the file on every scan, so no
restart is needed for the new list to take effect.

Symbol format matches the existing universe file exactly: bare uppercase
tickers, one per line, no ``.JK`` suffix.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

# A valid IDX ticker is 4 uppercase letters (a handful are 4 alnum). Used to
# filter junk out of any upstream payload before we trust it.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{3}$")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _normalize(symbols: List[str]) -> List[str]:
    """Uppercase, strip .JK, dedupe, keep only plausible IDX tickers, sort."""
    seen = set()
    out: List[str] = []
    for raw in symbols:
        if not raw:
            continue
        s = str(raw).strip().upper()
        if s.endswith(".JK"):
            s = s[:-3]
        if not _TICKER_RE.match(s):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Tier fetchers — each returns a normalized symbol list, or [] on any failure.
# Blocking httpx is fine; callers run fetch_current_symbols in an executor.
# ---------------------------------------------------------------------------

def _fetch_idx() -> List[str]:
    """Tier (a): IDX official securities-stock endpoint."""
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MAI-IDX-Signal/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.idx.co.id/en/market-data/stocks-data/stock-list/",
    }
    resp = httpx.get(
        settings.IDX_LISTED_URL, headers=headers, timeout=20.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    # Response shape: {"data": [{"Code": "BBCA", ...}, ...]} (key casing varies).
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    syms: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            code = row.get("Code") or row.get("code") or row.get("StockCode")
            if code:
                syms.append(code)
    return _normalize(syms)


def _fetch_stockbit() -> List[str]:
    """Tier (b): Stockbit company list (best-effort, may need auth).

    If a session cookie/token is required but not configured, returns [] so
    the caller falls through to the next tier instead of erroring.
    """
    import httpx

    cookie = settings.STOCKBIT_SESSION_COOKIE.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MAI-IDX-Signal/1.0)",
        "Accept": "application/json",
    }
    if cookie:
        # Accept either a raw bearer token or a full Cookie string.
        if cookie.lower().startswith("bearer ") or "." in cookie and " " not in cookie:
            headers["Authorization"] = (
                cookie if cookie.lower().startswith("bearer ") else f"Bearer {cookie}"
            )
        else:
            headers["Cookie"] = cookie

    resp = httpx.get(
        settings.STOCKBIT_UNIVERSE_URL, headers=headers, timeout=20.0,
        follow_redirects=True,
    )
    if resp.status_code in (401, 403):
        logger.info("Stockbit universe needs auth (HTTP %s) — skipping tier", resp.status_code)
        return []
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data") if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = rows.get("companies") or rows.get("list") or []
    if not isinstance(rows, list):
        return []
    syms: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            code = row.get("symbol") or row.get("code") or row.get("ticker")
            if code:
                syms.append(code)
        elif isinstance(row, str):
            syms.append(row)
    return _normalize(syms)


def _fetch_yahoo() -> List[str]:
    """Tier (c): Yahoo Finance fallback — screen IDX-listed equities.

    Yahoo has no clean "all IDX tickers" endpoint; we page its equity screener
    filtered to exchange JKT. Best-effort final fallback.
    """
    import httpx

    base = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MAI-IDX-Signal/1.0)"}
    syms: List[str] = []
    # Page through results; the screener caps count per request.
    for offset in range(0, 1200, 250):
        params = {
            "formatted": "false",
            "scrIds": "all_cryptocurrencies_us",  # placeholder; replaced below
            "count": "250",
            "start": str(offset),
        }
        # Use a query screener filtered to the Jakarta exchange instead.
        url = (
            "https://query1.finance.yahoo.com/v1/finance/screener"
            f"?count=250&start={offset}"
        )
        body = {
            "size": 250,
            "offset": offset,
            "sortField": "intradaymarketcap",
            "sortType": "DESC",
            "quoteType": "EQUITY",
            "query": {
                "operator": "AND",
                "operands": [{"operator": "EQ", "operands": ["exchange", "JKT"]}],
            },
        }
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("yahoo screener page %s failed: %s", offset, exc)
            break
        quotes = (
            data.get("finance", {})
            .get("result", [{}])[0]
            .get("quotes", [])
        )
        if not quotes:
            break
        for q in quotes:
            sym = q.get("symbol", "")
            if sym:
                syms.append(sym)
        if len(quotes) < 250:
            break
    return _normalize(syms)


# Tier order. Functions resolved by name at call time (via module globals)
# so tests can monkeypatch the individual _fetch_* attributes.
_TIER_NAMES = [("idx", "_fetch_idx"), ("stockbit", "_fetch_stockbit"), ("yahoo", "_fetch_yahoo")]


def fetch_current_symbols() -> Tuple[List[str], str]:
    """Run the 3-tier fallback. Returns (symbols, source_name).

    The first tier that yields a non-empty normalized list wins. Returns
    ([], "none") if all tiers fail.
    """
    for name, fn_name in _TIER_NAMES:
        fn = globals()[fn_name]
        try:
            syms = fn()
        except Exception as exc:
            logger.warning("universe tier %s failed: %s", name, exc)
            continue
        if syms:
            logger.info("universe source=%s symbols=%d", name, len(syms))
            return syms, name
    return [], "none"


# ---------------------------------------------------------------------------
# Diff + safe write
# ---------------------------------------------------------------------------

def diff_universe(old: List[str], new: List[str]) -> Tuple[List[str], List[str]]:
    """Return (added, removed) sorted. added=IPO, removed=delisting."""
    old_set = set(old)
    new_set = set(new)
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    return added, removed


def _backup_dir() -> str:
    if settings.UNIVERSE_BACKUP_DIR:
        return settings.UNIVERSE_BACKUP_DIR
    return os.path.join(os.path.dirname(settings.IDX_UNIVERSE_PATH) or ".", "universe_backups")


def _changes_log_path() -> str:
    if settings.UNIVERSE_CHANGES_LOG:
        return settings.UNIVERSE_CHANGES_LOG
    return os.path.join(
        os.path.dirname(settings.IDX_UNIVERSE_PATH) or ".", "universe_changes.jsonl"
    )


def _backup_file(path: str, stamp: str) -> Optional[str]:
    """Copy the current file to a timestamped backup. Returns backup path."""
    if not os.path.exists(path):
        return None
    backup_dir = _backup_dir()
    os.makedirs(backup_dir, exist_ok=True)
    base = os.path.basename(path)
    safe_stamp = stamp.replace(":", "").replace(".", "")
    backup_path = os.path.join(backup_dir, f"{base}.{safe_stamp}.bak")
    with open(path, "r", encoding="utf-8") as src:
        content = src.read()
    with open(backup_path, "w", encoding="utf-8") as dst:
        dst.write(content)
    return backup_path


def _atomic_write(path: str, symbols: List[str]) -> None:
    """Write the symbol list atomically (temp file + os.replace)."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f".{os.path.basename(path)}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(symbols) + "\n")
    os.replace(tmp, path)


def _append_change_log(entry: Dict) -> None:
    try:
        path = _changes_log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("change-log append failed: %s", exc)


def update_universe_file(
    path: Optional[str] = None,
    new_symbols: Optional[List[str]] = None,
) -> Dict:
    """Fetch (or accept) the current symbol list, diff, and safely rewrite.

    Returns a result dict:
      {status, source, old_count, new_count, added, removed, backup, error}

    status is one of:
      - "updated"   : file rewritten (changes applied)
      - "no_change" : list identical to current file
      - "aborted"   : sanity gate failed (empty / < min ratio) — old file kept
      - "error"     : fetch failed entirely
    """
    from app.data.universe import load_universe

    path = path or settings.IDX_UNIVERSE_PATH
    old = load_universe(path)
    old_norm = _normalize(old)
    old_count = len(old_norm)

    if new_symbols is None:
        new_symbols, source = fetch_current_symbols()
    else:
        new_symbols, source = _normalize(new_symbols), "provided"

    result: Dict = {
        "status": "error",
        "source": source,
        "old_count": old_count,
        "new_count": len(new_symbols),
        "added": [],
        "removed": [],
        "backup": None,
        "error": None,
    }

    # Sanity gate: refuse to apply an empty or suspiciously-small list.
    if not new_symbols:
        result["status"] = "error"
        result["error"] = "fetch returned no symbols"
        logger.warning("universe update aborted: empty fetch")
        return result

    min_count = int(old_count * settings.UNIVERSE_MIN_RATIO)
    if old_count > 0 and len(new_symbols) < min_count:
        result["status"] = "aborted"
        result["error"] = (
            f"new list too small ({len(new_symbols)} < {min_count} "
            f"= {settings.UNIVERSE_MIN_RATIO:.0%} of {old_count})"
        )
        logger.warning("universe update aborted: %s", result["error"])
        return result

    added, removed = diff_universe(old_norm, new_symbols)
    result["added"] = added
    result["removed"] = removed

    if not added and not removed:
        result["status"] = "no_change"
        logger.info("universe update: no change (%d symbols)", len(new_symbols))
        return result

    stamp = _utcnow_iso()
    backup = _backup_file(path, stamp)
    result["backup"] = backup
    _atomic_write(path, new_symbols)
    result["status"] = "updated"

    _append_change_log({
        "ts": stamp,
        "source": source,
        "old_count": old_count,
        "new_count": len(new_symbols),
        "added": added,
        "removed": removed,
        "backup": backup,
    })
    logger.info(
        "universe updated: +%d -%d (source=%s, %d->%d)",
        len(added), len(removed), source, old_count, len(new_symbols),
    )
    return result
