"""Stockbit fundamental + foreign-flow fetch (async httpx).

Two best-effort fetchers used by the deep-analysis path:
  * fetch_keystats(symbol)      -> flat dict of ~21 fundamental fields (or {})
  * fetch_foreign_flow(symbol)  -> DataFrame[date,foreign_buy,foreign_sell,foreign_net] (or empty)

Neither raises. On 401/403/timeout/parse-fail they degrade to {}/empty so a
scan is never failed by Stockbit. Symbols are stripped of .JK/.JKT and
uppercased before hitting Stockbit (Yahoo uses BBCA.JK, Stockbit uses BBCA).
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from app.data.stockbit_auth import auth_headers, get_token

logger = logging.getLogger(__name__)

BASE = "https://exodus.stockbit.com"
_TIMEOUT = 10.0

FOREIGN_COLS = ["date", "foreign_buy", "foreign_sell", "foreign_net"]

# Label substrings (lowercased) -> normalized field key. Stockbit keystats
# nests values under labelled rows; we walk defensively and match by label.
_LABEL_MAP = {
    "current pe": "per",
    "pe ratio": "per",
    "price to earning": "per",
    "current pbv": "pbv",
    "pbv": "pbv",
    "price to book": "pbv",
    "ev/ebitda": "ev_ebitda",
    "ev to ebitda": "ev_ebitda",
    "dividend yield": "div_yield",
    "eps": "eps_ttm",
    "earning per share": "eps_ttm",
    "bvps": "bvps",
    "book value per share": "bvps",
    "return on equity": "roe",
    "roe": "roe",
    "return on asset": "roa",
    "roa": "roa",
    "net profit margin": "net_margin",
    "net margin": "net_margin",
    "revenue": "rev_ttm",
    "net income": "ni_ttm",
    "ebitda": "ebitda",
    "total asset": "assets",
    "total equity": "equity",
    "cash": "cash",
    "debt to equity": "der",
    "der": "der",
    "current ratio": "cr",
    "operating cash flow": "ocf",
    "capital expenditure": "capex",
    "capex": "capex",
    "free cash flow": "fcf",
}

_ALL_FIELDS = [
    "per", "pbv", "ev_ebitda", "div_yield", "eps_ttm", "bvps", "roe", "roa",
    "net_margin", "rev_ttm", "rev_yoy", "ni_ttm", "ni_yoy", "ebitda", "assets",
    "equity", "cash", "der", "cr", "ocf", "capex", "fcf",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_symbol(symbol: str) -> str:
    """Strip Yahoo suffix and uppercase for Stockbit."""
    s = (symbol or "").strip().upper()
    for suf in (".JKT", ".JK"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s


def _num(v) -> Optional[float]:
    """Coerce Stockbit's stringy numbers to float. Handles '1.2x', '14.5%',
    '1,234', '-', '', None, '1.2T/B/M' suffixes. Returns None on failure."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return f if f == f else None  # drop NaN
        except Exception:
            return None
    s = str(v).strip()
    if not s or s in ("-", "N/A", "n/a", "NaN", "null"):
        return None
    mult = 1.0
    s = s.replace("x", "").replace("X", "")
    if s.endswith("%"):
        s = s[:-1]
    s = s.strip()
    # magnitude suffix
    if s and s[-1] in "TtBbMmKk":
        suf = s[-1].lower()
        mult = {"t": 1e12, "b": 1e9, "m": 1e6, "k": 1e3}.get(suf, 1.0)
        s = s[:-1]
    s = s.replace(",", "").replace(" ", "")
    if not s:
        return None
    try:
        return float(s) * mult
    except Exception:
        return None


def _walk(obj, out: Dict[str, float]) -> None:
    """Recursively walk JSON, matching labelled name/value pairs into out."""
    if isinstance(obj, dict):
        # name/value style row
        name = None
        for nk in ("name", "title", "label", "key"):
            if isinstance(obj.get(nk), str):
                name = obj[nk]
                break
        if name is not None:
            val = None
            for vk in ("value", "val", "amount", "current", "data", "raw"):
                if vk in obj and not isinstance(obj[vk], (dict, list)):
                    val = obj[vk]
                    break
            if val is not None:
                lname = name.lower()
                for lab, key in _LABEL_MAP.items():
                    if lab in lname and out.get(key) is None:
                        n = _num(val)
                        if n is not None:
                            out[key] = n
                        break
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _walk(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, out)


async def _get(path: str, token: str) -> Optional[dict]:
    """GET a Stockbit exodus path -> parsed JSON dict, or None on any failure."""
    if not token:
        return None
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available — skipping Stockbit fetch")
        return None
    url = f"{BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers=auth_headers(token))
        if resp.status_code in (401, 403):
            logger.warning("Stockbit auth rejected (%d) for %s", resp.status_code, path)
            return None
        if resp.status_code != 200:
            logger.debug("Stockbit %d for %s", resp.status_code, path)
            return None
        return resp.json()
    except Exception as exc:
        logger.debug("Stockbit fetch failed %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Public fetchers
# ---------------------------------------------------------------------------

async def fetch_keystats(symbol: str, token: Optional[str] = None) -> Dict:
    """Fetch + normalize Stockbit keystats into a flat dict of fundamentals.

    Returns {} on any failure. Never raises.
    """
    sym = _clean_symbol(symbol)
    if not sym:
        return {}
    tok = token if token is not None else get_token()
    data = await _get(f"/keystats/ratio/v1/{sym}", tok)
    if not data:
        return {}
    try:
        out: Dict[str, float] = {k: None for k in _ALL_FIELDS}
        _walk(data, out)
        # drop keys that stayed None to keep dict compact, but keep at least
        # what was found.
        found = {k: v for k, v in out.items() if v is not None}
        return found
    except Exception as exc:
        logger.debug("keystats parse failed for %s: %s", sym, exc)
        return {}


async def fetch_foreign_flow(symbol: str, token: Optional[str] = None) -> pd.DataFrame:
    """Fetch foreign buy/sell/net history as a DataFrame.

    Columns: date, foreign_buy, foreign_sell, foreign_net.
    Returns empty same-cols DataFrame on failure. Never raises.
    """
    empty = pd.DataFrame(columns=FOREIGN_COLS)
    sym = _clean_symbol(symbol)
    if not sym:
        return empty
    tok = token if token is not None else get_token()
    data = await _get(f"/company-price-feed/historical/summary/{sym}", tok)
    if not data:
        return empty
    try:
        # Find the list of daily rows — Stockbit nests under data/ result/ etc.
        rows = None
        if isinstance(data, dict):
            for k in ("data", "result", "results", "items", "summary", "history"):
                v = data.get(k)
                if isinstance(v, list) and v:
                    rows = v
                    break
                if isinstance(v, dict):
                    for k2 in ("data", "result", "items", "history", "list"):
                        v2 = v.get(k2)
                        if isinstance(v2, list) and v2:
                            rows = v2
                            break
                    if rows:
                        break
        elif isinstance(data, list):
            rows = data
        if not rows:
            return empty

        recs = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            dt = (r.get("date") or r.get("Date") or r.get("trade_date")
                  or r.get("time") or r.get("datetime"))
            fbuy = _num(r.get("foreign_buy") or r.get("foreignBuy")
                        or r.get("fbuy") or r.get("buy"))
            fsell = _num(r.get("foreign_sell") or r.get("foreignSell")
                         or r.get("fsell") or r.get("sell"))
            fnet = _num(r.get("foreign_net") or r.get("foreignNet")
                        or r.get("net_foreign") or r.get("netForeign")
                        or r.get("fnet") or r.get("net"))
            if fnet is None and fbuy is not None and fsell is not None:
                fnet = fbuy - fsell
            recs.append({
                "date": dt,
                "foreign_buy": fbuy if fbuy is not None else 0.0,
                "foreign_sell": fsell if fsell is not None else 0.0,
                "foreign_net": fnet if fnet is not None else 0.0,
            })
        if not recs:
            return empty
        df = pd.DataFrame(recs, columns=FOREIGN_COLS)
        try:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.sort_values("date")
        except Exception:
            pass
        return df
    except Exception as exc:
        logger.debug("foreign flow parse failed for %s: %s", sym, exc)
        return empty
