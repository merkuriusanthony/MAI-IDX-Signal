"""Tests for the backtest engine (Group C)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _make_df(periods: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=periods, freq="B")
    return pd.DataFrame({
        "Open": rng.uniform(1000, 1100, periods),
        "High": rng.uniform(1050, 1150, periods),
        "Low": rng.uniform(950, 1050, periods),
        "Close": rng.uniform(1000, 1100, periods),
        "Volume": rng.integers(1_000_000, 10_000_000, periods),
    }, index=idx)


def test_run_backtest_returns_list():
    from app.backtest.engine import run_backtest

    df = _make_df(100)
    results = run_backtest("BBCA", df, lookback=30, hold_max=5)
    assert isinstance(results, list)


def test_run_backtest_too_short():
    from app.backtest.engine import run_backtest

    df = _make_df(10)
    results = run_backtest("BBCA", df, lookback=30, hold_max=5)
    assert results == []


def test_summarize_empty_and_nonempty():
    from app.backtest.engine import summarize

    empty = summarize([])
    assert empty["total_signals"] == 0
    assert empty["win_rate"] == 0.0

    trades = [
        {"pnl_pct": 5.0}, {"pnl_pct": -3.0}, {"pnl_pct": 2.0},
    ]
    s = summarize(trades)
    assert s["total_signals"] == 3
    assert 0 <= s["win_rate"] <= 100
    assert s["worst_trade"] == -3.0           # was the mislabeled "max_drawdown"
    assert s["max_equity_drawdown"] <= 0.0    # true peak-to-trough equity DD
    assert s["profit_factor"] >= 0.0


def test_run_backtest_trades_do_not_overlap():
    """Regression: the walk-forward loop used to re-score every single
    bar, opening a new "trade" on top of one that hadn't exited yet
    (same symbol, same capital). That made _max_equity_drawdown()'s
    sequential-compounding assumption nonsense -- 1000+ overlapping
    trades on one unit of capital can compound into a fake -90%+
    drawdown even when the worst single trade is -10%.

    A strong, steady uptrend with occasional dips reliably fires BUY
    repeatedly across the series, which is exactly the overlap-prone
    shape. Assert each trade's entry is on/after the prior trade's exit.
    """
    from app.backtest.engine import run_backtest

    periods = 220
    idx = pd.date_range("2024-01-01", periods=periods, freq="B")
    # Steady uptrend with a small sawtooth so RSI/MA cross BUY repeatedly
    # instead of just once at the very start.
    t = np.arange(periods)
    base = 1000 + t * 3 + 40 * np.sin(t / 7.0)
    df = pd.DataFrame({
        "Open": base,
        "High": base * 1.015,
        "Low": base * 0.985,
        "Close": base,
        "Volume": np.full(periods, 5_000_000),
    }, index=idx)

    results = run_backtest("TEST", df, lookback=30, hold_max=10)
    assert len(results) >= 2, "need >=2 trades to check overlap"

    dates = [pd.Timestamp(r["entry_date"]) for r in results]
    exits = [pd.Timestamp(r["exit_date"]) for r in results]
    for k in range(1, len(results)):
        assert dates[k] >= exits[k - 1], (
            f"trade {k} entered {dates[k].date()} before trade {k-1} "
            f"exited {exits[k-1].date()} -- overlapping positions"
        )
