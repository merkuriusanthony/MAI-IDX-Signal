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
    """Tier (a): IDX official securities-stock list.

    IDX blocks datacenter IPs (Cloudflare 403). When IDX_PROXY_URL is set we
    fetch through a Cloudflare Worker proxy (residential-ish CF egress, not a
    DC IP), which returns the IDX JSON verbatim. Falls back to a direct call
    when no proxy is configured (works only from non-blocked IPs).
    """
    import httpx

    proxy = settings.IDX_PROXY_URL.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MAI-IDX-Signal/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.idx.co.id/en/market-data/stocks-data/stock-list/",
    }
    url = proxy if proxy else settings.IDX_LISTED_URL
    resp = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
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


def _stockbit_token() -> str:
    """Resolve a Stockbit access JWT.

    Priority:
      1. File at settings.STOCKBIT_ACCESS_FILE (written by the host token
         manager's daily refresh; mounted into the container at /app/data).
      2. settings.STOCKBIT_SESSION_COOKIE env (raw bearer or "Bearer ...").

    Returns "" if neither yields a token.
    """
    path = settings.STOCKBIT_ACCESS_FILE.strip()
    if path and os.path.exists(path):
        try:
            tok = open(path, "r", encoding="utf-8").read().strip()
            if tok:
                return tok[7:].strip() if tok.lower().startswith("bearer ") else tok
        except Exception as exc:
            logger.debug("stockbit access file read failed: %s", exc)
    cookie = settings.STOCKBIT_SESSION_COOKIE.strip()
    if cookie:
        return cookie[7:].strip() if cookie.lower().startswith("bearer ") else cookie
    return ""


def _fetch_stockbit() -> List[str]:
    """Tier (b): enumerate the IDX universe via Stockbit ``/search/v2``.

    Stockbit has no single company-list endpoint that works on datacenter IPs;
    the reliable path is the authenticated search endpoint, queried with each
    A-Z (and AA-ZZ) prefix and merged locally. Needs a bearer JWT; returns []
    if no token is configured so the caller falls through to Yahoo.
    """
    import string
    import time as _time

    import httpx

    token = _stockbit_token()
    if not token:
        logger.info("Stockbit universe: no access token configured — skipping tier")
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }
    base = settings.STOCKBIT_SEARCH_URL
    # 1-letter prefixes catch the bulk; 2-letter prefixes densify coverage.
    prefixes = list(string.ascii_uppercase)
    prefixes += [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase]
    syms: List[str] = []
    seen_auth_fail = False
    with httpx.Client(timeout=20.0, headers=headers) as client:
        for kw in prefixes:
            try:
                resp = client.get(base, params={"keyword": kw, "limit": 20})
            except Exception as exc:
                logger.debug("stockbit search %s failed: %s", kw, exc)
                continue
            if resp.status_code in (401, 403):
                seen_auth_fail = True
                logger.info("Stockbit search auth failed (HTTP %s) — aborting tier", resp.status_code)
                break
            if resp.status_code == 429:
                _time.sleep(1.0)
                continue
            if resp.status_code != 200:
                continue
            try:
                comps = resp.json().get("data", {}).get("companies", []) or []
            except Exception:
                continue
            for c in comps:
                code = c.get("id") or c.get("symbol")
                ctype = c.get("type", "")
                tradeable = c.get("is_tradeable", True)
                if not code:
                    continue
                if ctype in ("COMPANY_TYPE_REKSA_DANA", "COMPANY_TYPE_ETF"):
                    continue
                if tradeable is False:
                    continue
                syms.append(code)
            _time.sleep(0.12)  # rate-limit guard
    if seen_auth_fail and not syms:
        return []
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
    allow_removal: Optional[bool] = None,
) -> Dict:
    """Fetch (or accept) the current symbol list, diff, and safely rewrite.

    Returns a result dict:
      {status, source, old_count, new_count, added, removed, backup, error}

    status is one of:
      - "updated"   : file rewritten (changes applied)
      - "no_change" : list identical to current file
      - "aborted"   : sanity gate failed (empty / < min ratio) — old file kept
      - "error"     : fetch failed entirely

    Removal policy (user-decided): symbols are only DROPPED when the
    authoritative IDX official source confirms the list. Non-authoritative
    sources (Stockbit /search/v2, Yahoo) return only *tradeable* tickers, so a
    missing symbol may just be suspended/illiquid, not delisted. For those
    sources we run ADDITIVE-ONLY: new IPOs are added, nothing is removed.
    ``allow_removal`` overrides this heuristic when set explicitly.
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

    # Decide removal policy: only the authoritative IDX source (or an explicit
    # caller-provided list) may delist. Auto-fetched Stockbit/Yahoo lists are
    # additive-only because they return only *tradeable* tickers.
    if allow_removal is None:
        allow_removal = source in ("idx", "provided")

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

    if not allow_removal and removed:
        # Additive-only: keep every existing symbol, merge in the new ones.
        merged = sorted(set(old_norm) | set(new_symbols))
        new_symbols = merged
        result["removal_suppressed"] = removed  # report for visibility
        removed = []
        result["new_count"] = len(new_symbols)

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
        "removal_suppressed": result.get("removal_suppressed", []),
        "backup": backup,
    })
    logger.info(
        "universe updated: +%d -%d (source=%s, %d->%d)",
        len(added), len(removed), source, old_count, len(new_symbols),
    )
    return result
