"""Signal generation pipeline: fetch -> indicators -> score -> AI -> levels."""
from __future__ import annotations

from typing import Dict, List

from app.ai.claude_client import call_claude
from app.ai.prompts import build_signal_prompt
from app.analytics.indicators import atr, compute_all
from app.analytics.scoring import score as score_fn
from app.data.fetch_yahoo import fetch_ohlcv


def _levels(close: float, atr_val: float, label: str) -> Dict[str, float]:
    """Derive entry/TP/SL from close and ATR."""
    atr_val = atr_val if atr_val and atr_val > 0 else close * 0.02
    entry = round(close, 2)
    tp1 = round(close + 1.5 * atr_val, 2)
    tp2 = round(close + 3.0 * atr_val, 2)
    sl = round(close - 1.5 * atr_val, 2)
    return {"entry": entry, "tp1": tp1, "tp2": tp2, "sl": sl}


async def _build_one(symbol: str, with_ai: bool) -> Dict | None:
    df = fetch_ohlcv(symbol)
    if df is None or df.empty or len(df) < 20:
        return None

    indicators = compute_all(df)
    score_dict = score_fn(df, indicators)
    close = indicators["close"]
    atr_val = float(atr(df).iloc[-1])
    levels = _levels(close, atr_val, score_dict["label"])

    # Confidence scales with score.
    confidence = round(min(0.99, max(0.05, score_dict["score"] / 100.0)), 2)

    summary = ""
    reasons = list(score_dict["reasons"])
    if with_ai:
        prompt = build_signal_prompt(symbol, score_dict, indicators)
        ai = await call_claude(prompt)
        summary = ai.get("summary", "")
        if ai.get("key_reasons"):
            reasons = list(ai["key_reasons"]) + reasons

    return {
        "symbol": symbol,
        "label": score_dict["label"],
        "score": score_dict["score"],
        "confidence": confidence,
        "reasons": reasons,
        "summary": summary,
        **levels,
    }


async def generate_signals(
    symbols: List[str], top_n: int = 5, with_ai: bool = False
) -> List[Dict]:
    """Generate signals for a list of symbols and return the top ``top_n``.

    Sorted by score descending.
    """
    results: List[Dict] = []
    for sym in symbols:
        try:
            sig = await _build_one(sym, with_ai)
        except Exception:
            sig = None
        if sig:
            results.append(sig)

    results.sort(key=lambda s: s["score"], reverse=True)
    return results[:top_n]
