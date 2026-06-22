"""Signal generation pipeline: fetch -> features -> score -> levels."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.analytics.indicators import compute_features
from app.analytics.scoring import score_snapshot
from app.data.fetch_yahoo import fetch_ohlcv_safe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IDX tick size rounding
# ---------------------------------------------------------------------------

def _idx_tick(price: float) -> float:
    """Round price to IDX board lot tick size."""
    if price <= 0:
        return price
    if price < 200:
        tick = 1
    elif price < 500:
        tick = 2
    elif price < 2000:
        tick = 5
    elif price < 5000:
        tick = 10
    else:
        tick = 25
    return round(round(price / tick) * tick, 2)


# ---------------------------------------------------------------------------
# Entry / TP / SL calculation
# ---------------------------------------------------------------------------

def _levels(close: float, atr_val: float, support: float) -> Dict[str, float]:
    """Deterministic entry/TP/SL from close, ATR, support."""
    if not atr_val or atr_val <= 0:
        atr_val = close * 0.02

    entry = _idx_tick(close)
    risk = max(close - max(support * 0.98, close - 1.5 * atr_val), atr_val * 0.5)
    if risk <= 0:
        risk = close * 0.02

    tp1 = _idx_tick(entry + 1.5 * risk)
    tp2 = _idx_tick(entry + 2.5 * risk)
    sl = _idx_tick(entry - risk)
    invalidation = _idx_tick(max(support * 0.97, entry - 2.0 * atr_val))

    # Enforce validity
    if tp1 <= entry:
        tp1 = _idx_tick(entry * 1.02)
    if tp2 <= tp1:
        tp2 = _idx_tick(tp1 * 1.02)
    if sl >= entry:
        sl = _idx_tick(entry * 0.97)
    if invalidation >= sl:
        invalidation = _idx_tick(sl * 0.98)

    rr = (tp1 - entry) / (entry - sl) if (entry - sl) > 0 else 0
    return {
        "entry": entry,
        "tp1": tp1,
        "tp2": tp2,
        "stop_loss": sl,
        "sl": sl,
        "invalidation": invalidation,
        "risk_reward": round(rr, 2),
    }


# ---------------------------------------------------------------------------
# Single-symbol signal builder
# ---------------------------------------------------------------------------

async def _build_one(
    symbol: str,
    with_ai: bool = False,
    min_history: int = 20,
    min_rr: float = 1.2,
    precomputed_df=None,
    precomputed_snap=None,
    precomputed_value: Optional[float] = None,
) -> Optional[Dict]:
    # Reuse scanner-fetched data when available (kills double-fetch).
    if precomputed_df is not None and precomputed_snap is not None:
        df = precomputed_df
        snap = precomputed_snap
        value_estimate = precomputed_value if precomputed_value is not None else 0.0
    else:
        result = fetch_ohlcv_safe(symbol, min_rows=min_history)
        if not result["ok"]:
            logger.debug("skip %s: %s", symbol, result["error"])
            return None
        df = result["df"]
        snap = compute_features(df, symbol=symbol)
        value_estimate = result["value_estimate"]

    if not snap.data_ok:
        return None

    score_dict = score_snapshot(snap)
    levels = _levels(snap.close, snap.atr14 or snap.close * 0.02, snap.support)

    # Reject bad risk/reward
    if levels["risk_reward"] < min_rr and score_dict["action"] not in ("BUY", "WATCH"):
        logger.debug("skip %s: r/r %.2f < %.2f", symbol, levels["risk_reward"], min_rr)
        return None

    confidence = round(min(0.99, max(0.05, score_dict["score"] / 100.0)), 2)

    summary = ""
    if with_ai and score_dict["action"] in ("BUY", "WATCH"):
        try:
            from app.ai.claude_client import call_claude
            from app.ai.prompts import build_signal_prompt
            prompt = build_signal_prompt(symbol, score_dict, snap.to_dict())
            ai = await call_claude(prompt)
            summary = ai.get("summary", "")
            if ai.get("key_reasons") and not ai.get("_fallback"):
                score_dict["reasons"] = list(ai["key_reasons"]) + score_dict["reasons"]
        except Exception as exc:
            logger.warning("AI call failed for %s: %s", symbol, exc)

    return {
        "symbol": symbol,
        "action": score_dict["action"],
        "label": score_dict["action"],
        "timeframe": "daily",
        "score": score_dict["score"],
        "confidence": confidence,
        "reasons": score_dict["reasons"],
        "reason_codes": score_dict.get("reason_codes", []),
        "summary": summary,
        "entry": levels["entry"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "stop_loss": levels["stop_loss"],
        "sl": levels["stop_loss"],
        "invalidation": levels["invalidation"],
        "risk_reward": levels["risk_reward"],
        "close": snap.close,
        "volume": int(snap.volume_latest),
        "value_estimate": value_estimate,
        "rsi": snap.rsi14,
        "ma20": snap.ma20,
        "ma50": snap.ma50,
        "ma100": snap.ma100,
        "ma200": snap.ma200,
        "volume_ratio": snap.volume_ratio,
        "atr_pct": snap.atr_pct,
        "snapshot": snap.to_dict(),
        "chart_path": "",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_signals(
    symbols: List[str],
    top_n: int = 5,
    with_ai: bool = False,
) -> List[Dict]:
    """Generate signals for a list of symbols and return the top top_n by score."""
    results: List[Dict] = []
    for sym in symbols:
        try:
            sig = await _build_one(sym, with_ai=with_ai)
        except Exception as exc:
            logger.warning("generate_signals error for %s: %s", sym, exc)
            sig = None
        if sig:
            results.append(sig)

    results.sort(key=lambda s: s["score"], reverse=True)
    return results[:top_n]


async def generate_signal_single(
    symbol: str,
    with_ai: bool = False,
) -> Optional[Dict]:
    """Generate one signal for a single symbol."""
    try:
        return await _build_one(symbol, with_ai=with_ai)
    except Exception as exc:
        logger.error("generate_signal_single error for %s: %s", symbol, exc)
        return None
