"""Backtest engine: replay scoring on historical OHLCV, simulate TP/SL hits.

Cost model: IDX retail round-trip is modeled via ``fee_bps`` (per side, in basis
points) plus ``slippage_bps`` (per side). Defaults reflect typical IDX online-broker
economics: ~0.19% buy / ~0.29% sell commission (incl. 0.1% PPh final on sell) plus
conservative slippage on semi-liquid names. Every reported ``pnl_pct`` is NET of costs;
the gross figure is kept alongside for transparency.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from app.analytics.indicators import compute_features
from app.analytics.scoring import score_snapshot
from app.data.sectors import get_sector

# --- IDX realistic cost defaults (basis points, per side) ---
DEFAULT_BUY_FEE_BPS = 19.0    # 0.19% online-broker buy commission
DEFAULT_SELL_FEE_BPS = 29.0   # 0.29% sell commission incl. 0.1% PPh final
DEFAULT_SLIPPAGE_BPS = 20.0   # 0.20% per side, conservative for semi-liquid IDX names


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with lowercase OHLCV columns expected by compute_features."""
    rename = {
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    return out


def _apply_costs(
    entry: float,
    exit_price: float,
    buy_fee_bps: float,
    sell_fee_bps: float,
    slippage_bps: float,
) -> float:
    """Return NET pnl % after fees + slippage on both legs.

    Buy leg fills worse (higher) by slippage, sell leg fills worse (lower).
    Fees are charged on traded notional each side.
    """
    eff_entry = entry * (1 + slippage_bps / 10_000.0)
    eff_exit = exit_price * (1 - slippage_bps / 10_000.0)
    gross = (eff_exit - eff_entry) / eff_entry
    # fees as fraction of notional, charged each side
    fee_frac = (buy_fee_bps + sell_fee_bps) / 10_000.0
    net = gross - fee_frac
    return net * 100.0


def run_backtest(
    symbol: str,
    df: pd.DataFrame,
    lookback: int = 30,
    hold_max: int = 20,
    tp1_pct: float = 0.07,
    tp2_pct: float = 0.12,
    sl_pct: float = 0.05,
    buy_fee_bps: float = DEFAULT_BUY_FEE_BPS,
    sell_fee_bps: float = DEFAULT_SELL_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> List[Dict]:
    """Walk forward over df: at each bar score the prior window, and if it is a
    BUY simulate a trade over the next ``hold_max`` bars checking SL/TP1/TP2.

    Fill assumptions (pessimistic):
    - Intrabar order checks SL first (conservative on the downside).
    - On a gap-through-SL (bar opens below SL), fill at the bar OPEN, not the SL
      level — you cannot get filled at a price the market jumped past.
    - Within a bar, TP1 is checked before TP2 (conservative: book the nearer target).

    Returns a list of simulated-trade dicts with both gross and NET (post-cost) pnl.
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
            low = float(row["low"])
            high = float(row["high"])
            bar_open = float(row["open"])
            # SL first (conservative). Gap-through-SL fills at the bar open, worse.
            if low <= sl:
                fill = min(sl, bar_open) if bar_open < sl else sl
                outcome, exit_price, exit_date = "sl", fill, str(ts)[:10]
                break
            # TP1 before TP2 (conservative: book the nearer target within a bar).
            if high >= tp1:
                if high >= tp2:
                    outcome, exit_price, exit_date = "tp2", tp2, str(ts)[:10]
                else:
                    outcome, exit_price, exit_date = "tp1", tp1, str(ts)[:10]
                break

        gross_pnl = (exit_price - entry) / entry * 100
        net_pnl = _apply_costs(
            entry, exit_price, buy_fee_bps, sell_fee_bps, slippage_bps
        )
        results.append({
            "symbol": symbol,
            "entry_date": str(hist.index[-1])[:10],
            "exit_date": exit_date,
            "entry_price": round(entry, 2),
            "exit_price": round(exit_price, 2),
            "pnl_pct": round(net_pnl, 2),       # NET of costs — the headline number
            "gross_pnl_pct": round(gross_pnl, 2),
            "outcome": outcome,
            "score": score_dict["score"],
            "sector": sector,
        })

    return results


def _max_equity_drawdown(returns_pct: List[float]) -> float:
    """True peak-to-trough drawdown of a compounding equity curve built by
    taking each trade sequentially (1 unit of capital, fully recycled).
    Returns drawdown as a negative percentage (e.g. -18.4)."""
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns_pct:
        equity *= (1 + r / 100.0)
        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return round(max_dd * 100.0, 2)


def summarize(results: List[Dict]) -> Dict:
    """Compute aggregate metrics over a list of simulated trades (NET of costs)."""
    total = len(results)
    if total == 0:
        return {
            "total_signals": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "avg_gross_return": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_equity_drawdown": 0.0,
            "worst_trade": 0.0,
        }
    nets = [r["pnl_pct"] for r in results]
    grosses = [r.get("gross_pnl_pct", r["pnl_pct"]) for r in results]
    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p <= 0]
    avg_return = sum(nets) / total
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "total_signals": total,
        "win_rate": round(len(wins) / total * 100, 2),
        "avg_return": round(avg_return, 2),               # NET expectancy per trade
        "avg_gross_return": round(sum(grosses) / total, 2),
        "expectancy": round(avg_return, 2),               # alias: net avg per trade
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
        "max_equity_drawdown": _max_equity_drawdown(nets),  # true peak-to-trough
        "worst_trade": round(min(nets), 2),               # was mislabeled "max_drawdown"
    }
