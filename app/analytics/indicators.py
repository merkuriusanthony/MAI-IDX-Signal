"""Technical indicators. All functions take an OHLCV DataFrame.

Expected columns (lowercase): open, high, low, close, volume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Low-level indicator functions
# ---------------------------------------------------------------------------

def ma(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Simple moving average of close over n periods. Returns None vals when insufficient."""
    return df["close"].rolling(window=n, min_periods=n).mean()


def rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder). Returns 50 when insufficient."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    # Wilder RSI edge cases:
    # - no losses and some gains => RSI 100 (strong monotonic rise)
    # - no gains and some losses => RSI 0
    # - no movement => neutral 50
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    out = out.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    out = out.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return out


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
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
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


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> Dict[str, pd.Series]:
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
    """Fibonacci retracement levels over the last bars candles."""
    window = df.tail(bars)
    if window.empty:
        return {}
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    diff = hi - lo
    if diff == 0:
        return {"0.0": hi, "0.5": hi, "1.0": lo}
    return {
        "0.0": hi,
        "0.236": hi - 0.236 * diff,
        "0.382": hi - 0.382 * diff,
        "0.5": hi - 0.5 * diff,
        "0.618": hi - 0.618 * diff,
        "0.786": hi - 0.786 * diff,
        "1.0": lo,
    }


# ---------------------------------------------------------------------------
# FeatureSnapshot — full indicator state for one symbol at one point in time
# ---------------------------------------------------------------------------

@dataclass
class FeatureSnapshot:
    symbol: str = ""
    close: float = 0.0
    # MAs — None when insufficient history
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma100: Optional[float] = None
    ma200: Optional[float] = None
    # Momentum
    rsi14: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    # Volatility
    atr14: Optional[float] = None
    atr_pct: Optional[float] = None
    # Volume
    volume_latest: float = 0.0
    volume_avg20: float = 0.0
    volume_ratio: float = 0.0
    # Breakout flags
    breakout_20d: bool = False
    breakdown_20d: bool = False
    high_20d: float = 0.0
    low_20d: float = 0.0
    # Support/resistance
    support: float = 0.0
    resistance: float = 0.0
    # Fibonacci
    fib: Dict[str, float] = field(default_factory=dict)
    # Reason flags
    reason_flags: List[str] = field(default_factory=list)
    # Data quality
    bars_available: int = 0
    data_ok: bool = False

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "close": self.close,
            "ma5": self.ma5,
            "ma20": self.ma20,
            "ma50": self.ma50,
            "ma100": self.ma100,
            "ma200": self.ma200,
            "rsi": self.rsi14,
            "macd": self.macd_line,
            "macd_signal": self.macd_signal,
            "macd_hist": self.macd_hist,
            "stoch_k": self.stoch_k,
            "stoch_d": self.stoch_d,
            "atr": self.atr14,
            "atr_pct": self.atr_pct,
            "volume_spike": {
                "latest": self.volume_latest,
                "avg": self.volume_avg20,
                "ratio": self.volume_ratio,
            },
            "breakout_20d": self.breakout_20d,
            "breakdown_20d": self.breakdown_20d,
            "high_20d": self.high_20d,
            "low_20d": self.low_20d,
            "support_resistance": {
                "support": self.support,
                "resistance": self.resistance,
            },
            "fib": self.fib,
            "reason_flags": self.reason_flags,
            "bars_available": self.bars_available,
        }


def compute_features(df: pd.DataFrame, symbol: str = "") -> FeatureSnapshot:
    """Compute full FeatureSnapshot from OHLCV DataFrame.

    Returns snapshot with data_ok=False if too few bars.
    """
    snap = FeatureSnapshot(symbol=symbol)
    snap.bars_available = len(df)

    if df.empty or len(df) < 5:
        return snap

    snap.data_ok = True
    snap.close = float(df["close"].iloc[-1])

    def _last(series: pd.Series) -> Optional[float]:
        v = series.iloc[-1]
        return float(v) if not pd.isna(v) else None

    snap.ma5 = _last(ma(df, 5))
    snap.ma20 = _last(ma(df, 20))
    snap.ma50 = _last(ma(df, 50))
    snap.ma100 = _last(ma(df, 100))
    snap.ma200 = _last(ma(df, 200))

    rsi_s = rsi(df, 14)
    snap.rsi14 = _last(rsi_s)

    macd_d = macd(df)
    snap.macd_line = _last(macd_d["macd"])
    snap.macd_signal = _last(macd_d["signal"])
    snap.macd_hist = _last(macd_d["hist"])

    stoch_d = stochastic(df)
    snap.stoch_k = _last(stoch_d["k"])
    snap.stoch_d = _last(stoch_d["d"])

    atr_s = atr(df, 14)
    snap.atr14 = _last(atr_s)
    if snap.atr14 and snap.close:
        snap.atr_pct = round(snap.atr14 / snap.close * 100, 2)

    vs = volume_spike(df, 20)
    snap.volume_latest = vs["latest"]
    snap.volume_avg20 = vs["avg"]
    snap.volume_ratio = vs["ratio"]

    # 20d high/low breakout
    window20 = df.tail(20)
    snap.high_20d = float(window20["high"].max())
    snap.low_20d = float(window20["low"].min())
    prev_high_20d = float(df.iloc[:-1].tail(20)["high"].max()) if len(df) > 1 else snap.high_20d
    snap.breakout_20d = snap.close >= prev_high_20d and snap.close > 0
    snap.breakdown_20d = snap.close <= snap.low_20d

    sr = support_resistance(df, 60)
    snap.support = sr["support"]
    snap.resistance = sr["resistance"]
    snap.fib = fib_retracement(df, 120)

    # populate reason flags
    flags = snap.reason_flags
    if snap.ma20 and snap.close > snap.ma20:
        flags.append("TREND_UP")
    if snap.ma20 and snap.ma50 and snap.ma20 > snap.ma50:
        flags.append("MA_STACK_BULLISH")
    if snap.volume_ratio >= 2.0:
        flags.append("VOLUME_SPIKE")
    if snap.breakout_20d:
        flags.append("BREAKOUT_20D")
    if snap.rsi14 and 50 <= snap.rsi14 <= 70:
        flags.append("RSI_HEALTHY")
    if snap.rsi14 and snap.rsi14 > 70:
        flags.append("RSI_OVERBOUGHT")
    if snap.macd_hist and snap.macd_hist > 0:
        flags.append("MACD_POSITIVE")
    if snap.atr_pct and snap.atr_pct > 5:
        flags.append("ATR_HIGH")
    if snap.breakdown_20d:
        flags.append("BREAKDOWN_20D")

    return snap


# ---------------------------------------------------------------------------
# Legacy compute_all — kept for backward compat with existing callers
# ---------------------------------------------------------------------------

def compute_all(df: pd.DataFrame) -> Dict[str, object]:
    """Legacy convenience function: compute the full indicator set."""
    snap = compute_features(df)
    return snap.to_dict()
