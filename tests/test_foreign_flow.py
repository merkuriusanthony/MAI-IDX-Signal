"""Tests for Phase 5.5 foreign broker-flow scoring confirmation."""
from __future__ import annotations

import pandas as pd
import pytest

from app.analytics.foreign_flow import foreign_flow_adjust


def _df(nets, buys=None, sells=None):
    n = len(nets)
    buys = buys if buys is not None else [abs(x) + 1000 for x in nets]
    sells = sells if sells is not None else [abs(x) + 1000 for x in nets]
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "foreign_buy": buys,
        "foreign_sell": sells,
        "foreign_net": nets,
    })


def test_non_buy_action_untouched():
    df = _df([5000, 5000, 5000])
    score, reasons, codes = foreign_flow_adjust(df, "WATCH", 60.0)
    assert score == 60.0
    assert reasons == []
    assert codes == []


def test_empty_or_missing_df_fails_open():
    score, reasons, codes = foreign_flow_adjust(None, "BUY", 60.0)
    assert score == 60.0
    assert reasons == []

    score2, _, _ = foreign_flow_adjust(pd.DataFrame(), "BUY", 60.0)
    assert score2 == 60.0


def test_strong_foreign_net_buy_boosts_score():
    # net buy decisively dominant vs gross traded value
    df = _df([8000] * 5, buys=[9000] * 5, sells=[1000] * 5)
    score, reasons, codes = foreign_flow_adjust(df, "BUY", 60.0)
    assert score > 60.0
    assert "FLOW_FOREIGN_BUY_STRONG" in codes
    assert reasons


def test_strong_foreign_net_sell_penalizes_buy():
    df = _df([-8000] * 5, buys=[1000] * 5, sells=[9000] * 5)
    score, reasons, codes = foreign_flow_adjust(df, "BUY", 60.0)
    assert score < 60.0
    assert "FLOW_FOREIGN_SELL_STRONG" in codes


def test_adjustment_bounded():
    df = _df([100000] * 5, buys=[100001] * 5, sells=[1] * 5)
    score, _, _ = foreign_flow_adjust(df, "BUY", 95.0)
    assert score <= 100.0
    df_sell = _df([-100000] * 5, buys=[1] * 5, sells=[100001] * 5)
    score2, _, _ = foreign_flow_adjust(df_sell, "BUY", 5.0)
    assert score2 >= 0.0
