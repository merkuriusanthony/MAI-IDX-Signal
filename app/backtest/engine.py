"""Backtest engine: replay scoring on historical OHLCV, simulate TP/SL hits."""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from app.analytics.indicators import compute_features
from app.analytics.scoring import score_snapshot
from app.data.sectors import get_sector


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with lowercase OHLCV columns expected by compute_features."""
    rename = {
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    return out


def run_backtest(
    symbol: str,
    df: pd.DataFrame,
    lookback: int = 30,
    hold_max: int = 20,
    tp1_pct: float = 0.07,
    tp2_pct: float = 0.12,
    sl_pct: float = 0.05,
) -> List[Dict]:
    """Walk forward over df: at each bar score the prior window, and if it is a
    BUY simulate a trade over the next ``hold_max`` bars checking SL/TP2/TP1.
    Returns a list of simulated-trade dicts.
    """
    df = _normalize(df)
    if df.empty or len(df) < lookback + hold_max + 2:
        return []

    sector = get_sector(symbol)
    results: List[Dict] = []

    for i in range(lookback, len(df) - hold_max - 1):
        hist = df.iloc[:i]
        snap = compute_features(hist, symbol=symbol)
        if not snap.data_ok:
            continue
        score_dict = score_snapshot(snap)
        if score_dict["action"] != "BUY":
            continue

        entry = float(hist["close"].iloc[-1])
        if entry <= 0:
            continue
        tp1 = entry * (1 + tp1_pct)
        tp2 = entry * (1 + tp2_pct)
        sl = entry * (1 - sl_pct)

        future = df.iloc[i:i + hold_max]
        outcome = "expired"
        exit_price = float(future["close"].iloc[-1])
        exit_date = str(future.index[-1])[:10]
        for ts, row in future.iterrows():
            if float(row["low"]) <= sl:
                outcome, exit_price, exit_date = "sl", sl, str(ts)[:10]
                break
            if float(row["high"]) >= tp2:
                outcome, exit_price, exit_date = "tp2", tp2, str(ts)[:10]
                break
            if float(row["high"]) >= tp1:
                outcome, exit_price, exit_date = "tp1", tp1, str(ts)[:10]
                break

        pnl = (exit_price - entry) / entry * 100
        results.append({
            "symbol": symbol,
            "entry_date": str(hist.index[-1])[:10],
            "exit_date": exit_date,
            "entry_price": round(entry, 2),
            "exit_price": round(exit_price, 2),
            "pnl_pct": round(pnl, 2),
            "outcome": outcome,
            "score": score_dict["score"],
            "sector": sector,
        })

    return results


def summarize(results: List[Dict]) -> Dict:
    """Compute aggregate metrics over a list of simulated trades."""
    total = len(results)
    if total == 0:
        return {"total_signals": 0, "win_rate": 0.0, "avg_return": 0.0, "max_drawdown": 0.0}
    wins = sum(1 for r in results if r["pnl_pct"] > 0)
    avg_return = sum(r["pnl_pct"] for r in results) / total
    max_drawdown = min((r["pnl_pct"] for r in results), default=0.0)
    return {
        "total_signals": total,
        "win_rate": round(wins / total * 100, 2),
        "avg_return": round(avg_return, 2),
        "max_drawdown": round(max_drawdown, 2),
    }
