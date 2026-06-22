"""Yahoo Finance OHLCV fetcher with SQLite cache + parquet file cache."""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

PARQUET_CACHE_DIR = "/tmp/mai_idx_cache"
PARQUET_CACHE_TTL = 60 * 30  # 30 min
RETRY_ATTEMPTS = 3  # retry yfinance on 429 rate-limit with backoff
CACHE_VERSION = "v2adj"  # bump to invalidate stale caches (v2 = auto_adjust=True)


def _parquet_path(symbol: str, period: str, interval: str) -> str:
    safe = symbol.replace(".", "_")
    return os.path.join(PARQUET_CACHE_DIR, f"{safe}_{period}_{interval}_{CACHE_VERSION}.parquet")


def _read_parquet_cache(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > PARQUET_CACHE_TTL:
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _to_jk(symbol: str) -> str:
    s = symbol.upper().strip()
    # Index tickers (e.g. ^JKSE) and already-suffixed symbols pass through.
    if s.startswith("^") or s.endswith(".JK"):
        return s
    return f"{s}.JK"


def _strip_jk(symbol: str) -> str:
    s = symbol.upper().strip()
    return s[:-3] if s.endswith(".JK") else s


def fetch_ohlcv(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV for an IDX symbol.

    Returns DataFrame with lowercase columns: open high low close volume.
    Internal symbol (stripped of .JK) is stored as df.attrs['symbol'].
    Returns empty DataFrame on failure — never raises.
    """
    os.makedirs(PARQUET_CACHE_DIR, exist_ok=True)
    ticker_jk = _to_jk(symbol)
    internal = _strip_jk(symbol)
    parquet_path = _parquet_path(ticker_jk, period, interval)

    if use_cache:
        cached = _read_parquet_cache(parquet_path)
        if cached is not None and not cached.empty:
            cached.attrs["symbol"] = internal
            return cached

    try:
        import yfinance as yf

        raw = None
        last_exc: Optional[Exception] = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                raw = yf.download(
                    ticker_jk,
                    period=period,
                    interval=interval,
                    progress=False,
                    auto_adjust=True,  # split/dividend-adjust whole OHLC bar
                    timeout=15,
                )
                break
            except Exception as exc:  # retry on rate-limit, give up otherwise
                last_exc = exc
                if "429" in str(exc) and attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if raw is None and last_exc is not None:
            raise last_exc
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker_jk, exc)
        return _empty(internal)

    if raw is None or raw.empty:
        logger.debug("yfinance returned empty for %s", ticker_jk)
        return _empty(internal)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    })
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].dropna()

    if df.empty:
        return _empty(internal)

    try:
        df.to_parquet(parquet_path)
    except Exception:
        pass

    df.attrs["symbol"] = internal
    return df


def _empty(symbol: str) -> pd.DataFrame:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df.attrs["symbol"] = symbol
    return df


def fetch_ohlcv_safe(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    min_rows: int = 20,
) -> Dict:
    """Fetch with per-symbol error handling.

    Returns dict with keys:
    - symbol: internal ticker (no .JK)
    - df: DataFrame or None
    - ok: bool
    - error: str or None
    - close: last close or None
    - avg_volume_20: avg 20d volume
    - value_estimate: close * avg_volume_20
    """
    internal = _strip_jk(symbol)
    try:
        df = fetch_ohlcv(symbol, period=period, interval=interval)
    except Exception as exc:
        return _err(internal, str(exc))

    if df is None or df.empty or len(df) < min_rows:
        return _err(internal, f"insufficient data ({len(df) if df is not None else 0} rows)")

    close = float(df["close"].iloc[-1])
    avg_vol = float(df["volume"].tail(20).mean()) if "volume" in df.columns else 0.0
    value_est = close * avg_vol

    return {
        "symbol": internal,
        "df": df,
        "ok": True,
        "error": None,
        "close": close,
        "avg_volume_20": avg_vol,
        "value_estimate": value_est,
    }


def _err(symbol: str, msg: str) -> Dict:
    return {
        "symbol": symbol,
        "df": None,
        "ok": False,
        "error": msg,
        "close": None,
        "avg_volume_20": 0.0,
        "value_estimate": 0.0,
    }


def df_to_ohlcv_rows(symbol: str, df: pd.DataFrame) -> List[Dict]:
    """Convert a DataFrame to list of dicts suitable for save_ohlcv."""
    rows = []
    for idx, row in df.iterrows():
        date_str = str(idx)[:10] if hasattr(idx, "__str__") else str(idx)
        rows.append({
            "date": date_str,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": int(row.get("volume", 0)),
        })
    return rows
