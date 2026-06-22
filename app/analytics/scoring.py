"""Deterministic scoring engine.

Combines technical indicators into a 0-100 score and a categorical action.
Total possible: 100 points (with bonuses/penalties).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Union

import pandas as pd

from app.analytics.indicators import FeatureSnapshot

VALID_LABELS = {"BUY", "WATCH", "HOLD", "AVOID", "DANGER"}

# Score → action thresholds
# Phase 5.2: lowered by ~10 after removing 12 phantom points (sector+5/flow+7).
# Those constants used to inflate every score uniformly; thresholds were
# calibrated against the inflated scale. Removing the constants without
# lowering thresholds would collapse the alert population.
_THRESHOLDS = [
    (65, "BUY"),
    (50, "WATCH"),
    (38, "HOLD"),
    (25, "AVOID"),
]


def _action_for(score: float) -> str:
    for threshold, action in _THRESHOLDS:
        if score >= threshold:
            return action
    return "DANGER"


def gorengan_penalty(snap: dict) -> float:
    """Return 0-50 penalty points for gorengan (manipulation) characteristics.

    Expects a dict with keys: close, avg_value_20d, volume_ratio, atr_pct
    (fractional, e.g. 0.15 = 15%), daily_change_pct (fractional).
    """
    penalty = 0.0
    price = snap.get("close", 0)
    avg_value = snap.get("avg_value_20d", 0)
    vol_ratio = snap.get("volume_ratio", 1.0)
    atr_pct = snap.get("atr_pct", 0)
    daily_change = snap.get("daily_change_pct", 0)

    if price < 50:  # penny stock
        penalty += 20
    if avg_value < 500_000_000:  # very low liquidity (< 500jt)
        penalty += 15
    if vol_ratio > 10:  # extreme volume spike
        penalty += 15
    if atr_pct > 0.15:  # extreme volatility (ATR > 15%)
        penalty += 10
    if daily_change > 0.25:  # extreme single-day move (>25% up)
        penalty += 20

    return min(penalty, 50)


def score_snapshot(snap: FeatureSnapshot) -> Dict:
    """Score a FeatureSnapshot.

    Returns dict: score (0-100), action, reasons, reason_codes.
    """
    if not snap.data_ok:
        return {"score": 0.0, "action": "DANGER", "label": "DANGER",
                "reasons": ["Data tidak tersedia"], "reason_codes": []}

    points = 50.0
    reasons: List[str] = []
    reason_codes: List[str] = []
    close = snap.close

    # ------------------------------------------------------------------
    # Trend score 0–25
    # ------------------------------------------------------------------
    trend_pts = 0.0
    ma20 = snap.ma20
    ma50 = snap.ma50
    ma100 = snap.ma100
    ma200 = snap.ma200

    if ma20:
        if close > ma20:
            trend_pts += 6
            reasons.append("Harga di atas MA20 (tren jangka pendek naik)")
            reason_codes.append("TREND_UP")
        else:
            trend_pts -= 4
            reasons.append("Harga di bawah MA20")
    if ma50:
        if close > ma50:
            trend_pts += 5
            reasons.append("Harga di atas MA50")
        else:
            trend_pts -= 3
    if ma200:
        if close > ma200:
            trend_pts += 8
            reasons.append("Harga di atas MA200 (tren utama bullish)")
        else:
            trend_pts -= 6
            reasons.append("Harga di bawah MA200 (tren utama bearish)")
    if ma20 and ma50 and ma20 > ma50:
        trend_pts += 6
        reasons.append("MA20 di atas MA50 (struktur bullish)")
        reason_codes.append("MA_STACK_BULLISH")
    points += max(-25, min(25, trend_pts))

    # ------------------------------------------------------------------
    # Momentum score 0–20
    # ------------------------------------------------------------------
    mom_pts = 0.0
    rsi_val = snap.rsi14
    if rsi_val is not None:
        if 50 <= rsi_val <= 70:
            mom_pts += 8
            reasons.append(f"RSI sehat ({rsi_val:.0f}) momentum positif")
            reason_codes.append("RSI_HEALTHY")
        elif rsi_val > 70:
            mom_pts -= 5
            reasons.append(f"RSI overbought ({rsi_val:.0f}) risiko koreksi")
            reason_codes.append("RSI_OVERBOUGHT")
        elif rsi_val < 30:
            mom_pts -= 5
            reasons.append(f"RSI oversold ({rsi_val:.0f}) tren lemah")

    macd_hist = snap.macd_hist
    if macd_hist is not None:
        if macd_hist > 0:
            mom_pts += 7
            reasons.append("MACD histogram positif (momentum naik)")
            reason_codes.append("MACD_POSITIVE")
        else:
            mom_pts -= 4
            reasons.append("MACD histogram negatif")

    if snap.breakout_20d:
        mom_pts += 5
        reasons.append("Breakout high 20 hari")
        reason_codes.append("BREAKOUT_20D")
    if snap.breakdown_20d:
        mom_pts -= 8
        reasons.append("Breakdown low 20 hari")
        reason_codes.append("BREAKDOWN_20D")
    points += max(-20, min(20, mom_pts))

    # ------------------------------------------------------------------
    # Liquidity score 0–15
    # ------------------------------------------------------------------
    liq_pts = 0.0
    from app.config import settings
    min_val = settings.SCAN_MIN_AVG_VALUE
    value_est = snap.close * snap.volume_avg20 if snap.volume_avg20 else 0.0
    if value_est >= min_val:
        liq_pts += 7
    elif value_est > 0:
        liq_pts -= 5
        reasons.append("Likuiditas rendah (nilai transaksi kecil)")
        reason_codes.append("LOW_LIQUIDITY")

    vol_ratio = snap.volume_ratio
    if vol_ratio >= 2.0:
        liq_pts += 8
        reasons.append(f"Lonjakan volume {vol_ratio:.1f}x rata-rata")
        reason_codes.append("VOLUME_SPIKE")
    elif vol_ratio >= 1.3:
        liq_pts += 4
        reasons.append(f"Volume di atas rata-rata ({vol_ratio:.1f}x)")
    elif vol_ratio and vol_ratio < 0.7:
        liq_pts -= 4
        reasons.append("Volume sepi di bawah rata-rata")
    points += max(-15, min(15, liq_pts))

    # ------------------------------------------------------------------
    # Risk score (−15 to +15)
    # ------------------------------------------------------------------
    risk_pts = 0.0
    atr_pct = snap.atr_pct
    if atr_pct is not None:
        if atr_pct > 7:
            risk_pts -= 10
            reasons.append(f"ATR tinggi {atr_pct:.1f}% — volatilitas ekstrem")
            reason_codes.append("ATR_HIGH")
        elif atr_pct > 5:
            risk_pts -= 5
            reasons.append(f"ATR elevated {atr_pct:.1f}%")
            reason_codes.append("ATR_HIGH")
        elif atr_pct < 2:
            risk_pts += 5
            reasons.append("Volatilitas rendah — pergerakan stabil")

    support = snap.support
    if support and close and close > 0:
        dist_to_support = (close - support) / close * 100
        if dist_to_support <= 3:
            risk_pts += 7
            reasons.append("Harga dekat support — risiko terbatas")
        elif dist_to_support > 15:
            risk_pts -= 3

    stoch_k = snap.stoch_k
    if stoch_k is not None:
        if stoch_k < 20:
            risk_pts += 4
            reasons.append("Stochastic oversold, potensi rebound")
        elif stoch_k > 80:
            risk_pts -= 3
            reasons.append("Stochastic overbought")
    points += max(-15, min(15, risk_pts))

    # ------------------------------------------------------------------
    # Phase 5.2: phantom market/sector (+5) and flow (+7) buckets REMOVED.
    # They were hardcoded constants applied to every stock — pure offset,
    # zero discrimination. Real sector relative-strength / foreign-flow
    # integration is deferred (see PHASE5_RESEARCH.md §1). Until then we do
    # not gift free points. Thresholds lowered ~10 to compensate.
    # ------------------------------------------------------------------

    final = round(max(0.0, min(100.0, points)), 1)
    action = _action_for(final)

    # force DANGER on breakdown or extreme ATR
    if snap.breakdown_20d and atr_pct and atr_pct > 7:
        action = "DANGER"
        final = min(final, 25.0)

    return {
        "score": final,
        "action": action,
        "label": action,
        "reasons": reasons,
        "reason_codes": reason_codes,
    }


def score(df: pd.DataFrame, indicators: Dict) -> Dict:
    """Legacy entry point: takes raw indicators dict.

    Bridges old generator code to new FeatureSnapshot-based scoring.
    """
    from app.analytics.indicators import FeatureSnapshot

    close = float(indicators.get("close", df["close"].iloc[-1] if len(df) else 0.0))

    snap = FeatureSnapshot(
        symbol=str(indicators.get("symbol", "")),
        close=close,
        ma5=_f(indicators, "ma5"),
        ma20=_f(indicators, "ma20"),
        ma50=_f(indicators, "ma50"),
        ma100=_f(indicators, "ma100"),
        ma200=_f(indicators, "ma200"),
        rsi14=_f(indicators, "rsi"),
        macd_hist=_f(indicators, "macd_hist"),
        macd_line=_f(indicators, "macd"),
        macd_signal=_f(indicators, "macd_signal"),
        stoch_k=_f(indicators, "stoch_k"),
        stoch_d=_f(indicators, "stoch_d"),
        atr14=_f(indicators, "atr"),
        data_ok=True,
        bars_available=len(df),
    )

    # volume_spike
    vs = indicators.get("volume_spike", {}) or {}
    if isinstance(vs, dict):
        snap.volume_latest = float(vs.get("latest", 0))
        snap.volume_avg20 = float(vs.get("avg", 0))
        snap.volume_ratio = float(vs.get("ratio", 0))

    # ATR pct
    if snap.atr14 and snap.close:
        snap.atr_pct = snap.atr14 / snap.close * 100

    # support
    sr = indicators.get("support_resistance", {}) or {}
    if isinstance(sr, dict):
        snap.support = float(sr.get("support", 0))
        snap.resistance = float(sr.get("resistance", 0))

    # breakout (need df for 20d high)
    if len(df) >= 20:
        high_20 = float(df["high"].tail(20).max())
        snap.breakout_20d = snap.close >= high_20
        snap.breakdown_20d = snap.close <= float(df["low"].tail(20).min())

    return score_snapshot(snap)


def _f(d: Dict, key: str) -> Optional[float]:
    v = d.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        return f if not (f != f) else None  # nan check
    except (TypeError, ValueError):
        return None
