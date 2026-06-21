"""Deterministic scoring engine.

Combines technical indicators into a 0-100 score and a categorical label.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

VALID_LABELS = {"BUY", "WATCH", "HOLD", "AVOID", "DANGER"}


def _label_for(score: float) -> str:
    if score >= 75:
        return "BUY"
    if score >= 60:
        return "WATCH"
    if score >= 45:
        return "HOLD"
    if score >= 30:
        return "AVOID"
    return "DANGER"


def score(df: pd.DataFrame, indicators: Dict[str, object]) -> Dict[str, object]:
    """Score a symbol from its computed indicators.

    Returns a dict with keys: ``score`` (0-100), ``label``, ``reasons``.
    """
    points = 50.0
    reasons: List[str] = []

    close = float(indicators.get("close", df["close"].iloc[-1] if len(df) else 0.0))

    # Trend: price above MAs
    ma20 = float(indicators.get("ma20", 0.0))
    ma50 = float(indicators.get("ma50", 0.0))
    ma200 = float(indicators.get("ma200", 0.0))
    if ma20 and close > ma20:
        points += 6
        reasons.append("Harga di atas MA20 (tren jangka pendek naik)")
    else:
        points -= 4
        reasons.append("Harga di bawah MA20")
    if ma50 and close > ma50:
        points += 6
        reasons.append("Harga di atas MA50")
    if ma200 and close > ma200:
        points += 8
        reasons.append("Harga di atas MA200 (tren utama bullish)")
    elif ma200:
        points -= 6
        reasons.append("Harga di bawah MA200 (tren utama bearish)")

    # RSI
    rsi_val = float(indicators.get("rsi", 50.0))
    if 50 <= rsi_val <= 70:
        points += 8
        reasons.append(f"RSI sehat ({rsi_val:.0f}) momentum positif")
    elif rsi_val > 70:
        points -= 5
        reasons.append(f"RSI overbought ({rsi_val:.0f}) risiko koreksi")
    elif rsi_val < 30:
        points -= 5
        reasons.append(f"RSI oversold ({rsi_val:.0f}) tren lemah")

    # MACD
    macd_hist = float(indicators.get("macd_hist", 0.0))
    if macd_hist > 0:
        points += 7
        reasons.append("MACD histogram positif (momentum naik)")
    else:
        points -= 4
        reasons.append("MACD histogram negatif")

    # Volume
    vol = indicators.get("volume_spike", {}) or {}
    ratio = float(vol.get("ratio", 0.0)) if isinstance(vol, dict) else 0.0
    if ratio >= 2.0:
        points += 10
        reasons.append(f"Lonjakan volume {ratio:.1f}x rata-rata")
    elif ratio >= 1.3:
        points += 5
        reasons.append(f"Volume di atas rata-rata ({ratio:.1f}x)")
    elif ratio and ratio < 0.7:
        points -= 4
        reasons.append("Volume sepi di bawah rata-rata")

    # Stochastic
    stoch_k = float(indicators.get("stoch_k", 50.0))
    if stoch_k < 20:
        points += 4
        reasons.append("Stochastic oversold, potensi rebound")
    elif stoch_k > 80:
        points -= 3
        reasons.append("Stochastic overbought")

    final = max(0.0, min(100.0, points))
    return {
        "score": round(final, 1),
        "label": _label_for(final),
        "reasons": reasons,
    }
