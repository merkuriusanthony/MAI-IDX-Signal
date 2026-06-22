"""Tests for Phase 5.3 archetype scoring + multi-timeframe (MTF) filter."""
import numpy as np
import pandas as pd

from app.analytics.archetype import (
    BALANCED,
    MEAN_REV,
    MOMENTUM,
    archetype_adjust,
    archetype_for_regime,
    mtf_weekly_filter,
    to_weekly,
)


class _Snap:
    """Minimal stand-in for FeatureSnapshot."""
    def __init__(self, **kw):
        self.close = kw.get("close", 1000.0)
        self.rsi14 = kw.get("rsi14")
        self.support = kw.get("support", 0.0)
        self.resistance = kw.get("resistance", 0.0)
        self.breakout_20d = kw.get("breakout_20d", False)
        self.macd_hist = kw.get("macd_hist")
        self.stoch_k = kw.get("stoch_k")


# --- archetype selection --------------------------------------------------

def test_archetype_for_regime_mapping():
    assert archetype_for_regime("risk_on") == MOMENTUM
    assert archetype_for_regime("risk_off") == MEAN_REV
    assert archetype_for_regime("neutral") == BALANCED


def test_archetype_fails_open_to_balanced():
    assert archetype_for_regime("risk_on", regime_ok=False) == BALANCED
    assert archetype_for_regime("weird") == BALANCED


# --- momentum archetype ---------------------------------------------------

def test_momentum_rewards_breakout():
    snap = _Snap(breakout_20d=True, macd_hist=1.0, rsi14=60)
    score, reasons, codes = archetype_adjust(snap, 60.0, MOMENTUM)
    assert score > 60.0
    assert "ARCH_MOM_BREAKOUT" in codes


def test_momentum_penalizes_oversold():
    snap = _Snap(rsi14=30, breakout_20d=False)
    score, _, _ = archetype_adjust(snap, 60.0, MOMENTUM)
    assert score < 60.0


# --- mean-reversion archetype ---------------------------------------------

def test_mean_rev_rewards_oversold_near_support():
    snap = _Snap(rsi14=30, stoch_k=15, close=1000, support=980)
    score, reasons, codes = archetype_adjust(snap, 50.0, MEAN_REV)
    assert score > 50.0
    assert "ARCH_MR_OVERSOLD" in codes
    assert "ARCH_MR_NEAR_SUPPORT" in codes


def test_mean_rev_punishes_chasing_breakout():
    snap = _Snap(rsi14=72, breakout_20d=True, close=1000, support=900)
    score, reasons, codes = archetype_adjust(snap, 70.0, MEAN_REV)
    assert score < 70.0
    assert "ARCH_MR_AVOID_CHASE" in codes


# --- adjustment is bounded ------------------------------------------------

def test_adjust_bounded_pm12():
    snap = _Snap(rsi14=30, stoch_k=10, close=1000, support=995,
                 breakout_20d=False, macd_hist=1.0)
    score, _, _ = archetype_adjust(snap, 50.0, MEAN_REV)
    assert 38.0 <= score <= 62.0  # base +/- 12 max


# --- weekly resample + MTF gate -------------------------------------------

def _daily_df(n=200, trend=1.0):
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    base = np.linspace(1000, 1000 * trend, n)
    return pd.DataFrame({
        "open": base, "high": base * 1.01, "low": base * 0.99,
        "close": base, "volume": np.full(n, 1_000_000.0),
    }, index=idx)


def test_to_weekly_resamples():
    wk = to_weekly(_daily_df(200))
    assert wk is not None
    assert len(wk) >= 20
    assert "close" in wk.columns


def test_mtf_passes_buy_in_uptrend():
    df = _daily_df(200, trend=1.5)  # strong uptrend, weekly close > MA20
    action, gated, note = mtf_weekly_filter(df, "BUY")
    assert action == "BUY"
    assert not gated


def test_mtf_downgrades_buy_in_downtrend():
    df = _daily_df(200, trend=0.6)  # downtrend, weekly close < MA20
    action, gated, note = mtf_weekly_filter(df, "BUY")
    assert action == "WATCH"
    assert gated
    assert "mingguan" in note


def test_mtf_only_affects_buy():
    df = _daily_df(200, trend=0.6)
    for act in ("WATCH", "HOLD", "AVOID", "DANGER"):
        a, g, _ = mtf_weekly_filter(df, act)
        assert a == act and not g


def test_mtf_fails_open_short_df():
    df = _daily_df(10)
    action, gated, _ = mtf_weekly_filter(df, "BUY")
    assert action == "BUY" and not gated
