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
