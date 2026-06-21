"""Yahoo Finance OHLCV fetcher with a simple on-disk cache."""
from __future__ import annotations

import os
import time
from typing import Optional

import pandas as pd

CACHE_DIR = "/tmp/mai_idx_cache"
CACHE_TTL_SECONDS = 60 * 30  # 30 minutes


def _cache_path(symbol: str, period: str, interval: str) -> str:
    safe = symbol.replace(".", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{period}_{interval}.parquet")


def _read_cache(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > CACHE_TTL_SECONDS:
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def fetch_ohlcv(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV for an IDX symbol (auto-appends ``.JK``).

    Returns a DataFrame with columns: open, high, low, close, volume.
    Returns an empty DataFrame on failure.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    ticker = symbol if symbol.upper().endswith(".JK") else f"{symbol.upper()}.JK"
    path = _cache_path(ticker, period, interval)

    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    try:
        import yfinance as yf

        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    # yfinance may return a MultiIndex for the column level when one ticker.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].dropna()

    try:
        df.to_parquet(path)
    except Exception:
        pass

    return df
