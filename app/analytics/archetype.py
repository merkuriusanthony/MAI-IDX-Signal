"""Phase 5.3: signal archetypes + multi-timeframe (MTF) confirmation.

The deterministic scorer in ``scoring.py`` is a single additive model tuned
for *trend/momentum* (rewards price > MAs, breakouts, MACD up). That model
is correct in a risk-on tape but actively wrong in a risk-off/choppy tape,
where the highest-expectancy long is a *mean-reversion* bounce off support,
not chasing a 20d breakout into a downtrend.

This module adds two orthogonal, regime-aware layers on top of the base
score (it does NOT replace it — base score is the trend pillar):

1. ``archetype_adjust`` — picks an archetype from the market regime and
   nudges the score:
     * risk_on   -> MOMENTUM : reward breakout/MACD-up, mild OB tolerance.
     * risk_off  -> MEAN_REV : reward oversold-near-support, penalize
                               chasing extended breakouts.
     * neutral   -> BALANCED : small symmetric tweaks.

2. ``mtf_weekly_filter`` — resamples the daily frame to weekly bars and
   confirms the higher timeframe is not fighting the trade. A BUY whose
   weekly close is below the weekly MA20 (higher-TF downtrend) is a
   counter-trend bet; we downgrade it to WATCH.

Both fail open: missing data -> no change, never raises into a scan.
See PHASE5_RESEARCH.md §1 ("archetype split", "multi-timeframe filter").
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

MOMENTUM = "momentum"
MEAN_REV = "mean_reversion"
BALANCED = "balanced"


def archetype_for_regime(regime_name: str, regime_ok: bool = True) -> str:
    """Map a market regime to a scoring archetype.

    Fails open to BALANCED when regime is unknown.
    """
    if not regime_ok:
        return BALANCED
    if regime_name == "risk_on":
        return MOMENTUM
    if regime_name == "risk_off":
        return MEAN_REV
    return BALANCED


def archetype_adjust(snap, base_score: float, archetype: str) -> Tuple[float, list, list]:
    """Return (adjusted_score, extra_reasons, extra_codes) for the archetype.

    The adjustment is bounded to +/-12 so it tunes, never dominates, the
    base trend score. Reads only fields already on the FeatureSnapshot.
    """
    reasons: list = []
    codes: list = []
    adj = 0.0

    close = getattr(snap, "close", 0.0) or 0.0
    rsi = getattr(snap, "rsi14", None)
    support = getattr(snap, "support", 0.0) or 0.0
    resistance = getattr(snap, "resistance", 0.0) or 0.0
    breakout = getattr(snap, "breakout_20d", False)
    macd_hist = getattr(snap, "macd_hist", None)
    stoch_k = getattr(snap, "stoch_k", None)

    dist_support = ((close - support) / close * 100) if (close and support) else None

    if archetype == MOMENTUM:
        # Reward continuation; tolerate slightly hot RSI.
        if breakout:
            adj += 6
            reasons.append("Momentum: breakout 20d searah regime risk-on")
            codes.append("ARCH_MOM_BREAKOUT")
        if macd_hist is not None and macd_hist > 0:
            adj += 3
            codes.append("ARCH_MOM_MACD")
        if rsi is not None and 55 <= rsi <= 75:
            adj += 3
            reasons.append("Momentum: RSI kuat searah tren")
        # In momentum mode, oversold is weakness, not opportunity.
        if rsi is not None and rsi < 40:
            adj -= 4

    elif archetype == MEAN_REV:
        # Reward oversold dips near support; punish chasing extended moves.
        if rsi is not None and rsi <= 35:
            adj += 6
            reasons.append("Mean-reversion: RSI oversold, potensi pantulan")
            codes.append("ARCH_MR_OVERSOLD")
        if stoch_k is not None and stoch_k < 20:
            adj += 3
            codes.append("ARCH_MR_STOCH")
        if dist_support is not None and dist_support <= 5:
            adj += 4
            reasons.append("Mean-reversion: harga dekat support (risiko terbatas)")
            codes.append("ARCH_MR_NEAR_SUPPORT")
        # Chasing a breakout in a risk-off tape is the classic trap.
        if breakout:
            adj -= 6
            reasons.append("Mean-reversion: hindari kejar breakout di pasar risk-off")
            codes.append("ARCH_MR_AVOID_CHASE")
        if rsi is not None and rsi > 70:
            adj -= 4
            reasons.append("Mean-reversion: RSI overbought, rawan koreksi")

    else:  # BALANCED
        if rsi is not None and rsi > 75:
            adj -= 3
        if rsi is not None and rsi < 30:
            adj += 3
        if dist_support is not None and dist_support <= 4:
            adj += 2

    adj = max(-12.0, min(12.0, adj))
    new_score = max(0.0, min(100.0, base_score + adj))
    return round(new_score, 1), reasons, codes


# ---------------------------------------------------------------------------
# Multi-timeframe (weekly) confirmation
# ---------------------------------------------------------------------------

def to_weekly(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Resample a daily OHLCV frame to weekly (W-FRI) bars.

    Returns None if the frame lacks a usable DatetimeIndex or is too short.
    """
    if df is None or df.empty or len(df) < 30:
        return None
    work = df
    if not isinstance(work.index, pd.DatetimeIndex):
        for col in ("date", "Date", "datetime", "Datetime"):
            if col in work.columns:
                work = work.set_index(pd.to_datetime(work[col]))
                break
        else:
            return None
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    cols = {c: agg[c] for c in agg if c in work.columns}
    if "close" not in cols:
        return None
    try:
        wk = work.resample("W-FRI").agg(cols).dropna(subset=["close"])
    except Exception as exc:
        logger.debug("weekly resample failed: %s", exc)
        return None
    return wk if len(wk) >= 20 else None


def mtf_weekly_filter(df: pd.DataFrame, action: str) -> Tuple[str, bool, str]:
    """Higher-timeframe gate: downgrade a BUY fighting the weekly trend.

    A BUY whose weekly close sits below its weekly MA20 is counter-trend on
    the higher timeframe -> downgrade to WATCH. Only BUY is affected.
    Fails open (no change) when weekly data is unavailable.

    Returns (new_action, downgraded, note).
    """
    if action != "BUY":
        return action, False, ""
    wk = to_weekly(df)
    if wk is None:
        return action, False, ""
    wk_close = float(wk["close"].iloc[-1])
    wk_ma20 = float(wk["close"].rolling(20, min_periods=20).mean().iloc[-1])
    if wk_ma20 != wk_ma20:  # nan
        return action, False, ""
    if wk_close < wk_ma20:
        note = (f"BUY → WATCH (timeframe mingguan bearish): "
                f"close mingguan {wk_close:.0f} < MA20 mingguan {wk_ma20:.0f}")
        return "WATCH", True, note
    return action, False, ""
