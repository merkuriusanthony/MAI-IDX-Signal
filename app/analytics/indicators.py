"""Technical indicators. All functions take an OHLCV DataFrame.

Expected columns (lowercase): open, high, low, close, volume.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def ma(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Simple moving average of close over ``n`` periods."""
    return df["close"].rolling(window=n, min_periods=1).mean()


def rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> Dict[str, pd.Series]:
    """MACD line, signal line and histogram."""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "hist": hist}


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=1, adjust=False).mean()


def volume_spike(df: pd.DataFrame, n: int = 20) -> Dict[str, float]:
    """Ratio of latest volume vs rolling average volume."""
    avg = df["volume"].rolling(window=n, min_periods=1).mean()
    latest = float(df["volume"].iloc[-1])
    avg_latest = float(avg.iloc[-1]) if avg.iloc[-1] else 0.0
    ratio = (latest / avg_latest) if avg_latest else 0.0
    return {"latest": latest, "avg": avg_latest, "ratio": ratio}


def stochastic(
    df: pd.DataFrame, k: int = 14, d: int = 3
) -> Dict[str, pd.Series]:
    """Stochastic oscillator %K and %D."""
    low_min = df["low"].rolling(window=k, min_periods=1).min()
    high_max = df["high"].rolling(window=k, min_periods=1).max()
    denom = (high_max - low_min).replace(0.0, np.nan)
    pct_k = 100 * (df["close"] - low_min) / denom
    pct_k = pct_k.fillna(50.0)
    pct_d = pct_k.rolling(window=d, min_periods=1).mean()
    return {"k": pct_k, "d": pct_d}


def support_resistance(df: pd.DataFrame, lookback: int = 60) -> Dict[str, float]:
    """Naive support/resistance from recent swing low/high."""
    window = df.tail(lookback)
    if window.empty:
        return {"support": 0.0, "resistance": 0.0}
    return {
        "support": float(window["low"].min()),
        "resistance": float(window["high"].max()),
    }


def fib_retracement(df: pd.DataFrame, bars: int = 120) -> Dict[str, float]:
    """Fibonacci retracement levels over the last ``bars`` candles."""
    window = df.tail(bars)
    if window.empty:
        return {}
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    diff = hi - lo
    levels = {
        "0.0": hi,
        "0.236": hi - 0.236 * diff,
        "0.382": hi - 0.382 * diff,
        "0.5": hi - 0.5 * diff,
        "0.618": hi - 0.618 * diff,
        "0.786": hi - 0.786 * diff,
        "1.0": lo,
    }
    return levels


def compute_all(df: pd.DataFrame) -> Dict[str, object]:
    """Convenience: compute the full indicator set, latest values where scalar."""
    macd_d = macd(df)
    stoch_d = stochastic(df)
    return {
        "ma5": float(ma(df, 5).iloc[-1]),
        "ma20": float(ma(df, 20).iloc[-1]),
        "ma50": float(ma(df, 50).iloc[-1]),
        "ma100": float(ma(df, 100).iloc[-1]),
        "ma200": float(ma(df, 200).iloc[-1]),
        "rsi": float(rsi(df).iloc[-1]),
        "macd": float(macd_d["macd"].iloc[-1]),
        "macd_signal": float(macd_d["signal"].iloc[-1]),
        "macd_hist": float(macd_d["hist"].iloc[-1]),
        "atr": float(atr(df).iloc[-1]),
        "volume_spike": volume_spike(df),
        "stoch_k": float(stoch_d["k"].iloc[-1]),
        "stoch_d": float(stoch_d["d"].iloc[-1]),
        "support_resistance": support_resistance(df),
        "fib": fib_retracement(df),
        "close": float(df["close"].iloc[-1]),
    }
