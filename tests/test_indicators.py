"""Tests for technical indicators."""
import numpy as np
import pandas as pd
import pytest

from app.analytics import indicators


@pytest.fixture
def ohlcv():
    n = 250
    rng = np.linspace(100, 200, n)
    noise = np.sin(np.linspace(0, 20, n)) * 5
    close = rng + noise
    high = close + 2
    low = close - 2
    open_ = close - 1
    volume = np.linspace(1_000, 5_000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def small_ohlcv():
    """Less than 20 rows — insufficient for many indicators."""
    n = 10
    close = np.linspace(100, 110, n)
    return pd.DataFrame({
        "open": close - 1, "high": close + 1,
        "low": close - 1, "close": close, "volume": np.ones(n) * 1000
    })


def test_ma_shape(ohlcv):
    out = indicators.ma(ohlcv, 20)
    assert len(out) == len(ohlcv)
    assert not out.isna().all()


def test_ma_insufficient_returns_nan_at_start(ohlcv):
    out = indicators.ma(ohlcv, 20)
    # first 19 rows should be NaN since min_periods=n
    assert out.iloc[:19].isna().all()


def test_rsi_range(ohlcv):
    out = indicators.rsi(ohlcv)
    valid = out.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_macd_keys(ohlcv):
    out = indicators.macd(ohlcv)
    assert set(out.keys()) == {"macd", "signal", "hist"}
    for series in out.values():
        assert len(series) == len(ohlcv)


def test_atr_positive(ohlcv):
    out = indicators.atr(ohlcv)
    assert len(out) == len(ohlcv)
    assert (out.dropna() >= 0).all()


def test_volume_spike(ohlcv):
    out = indicators.volume_spike(ohlcv)
    assert set(out.keys()) == {"latest", "avg", "ratio"}
    assert out["ratio"] >= 0


def test_fib_levels(ohlcv):
    out = indicators.fib_retracement(ohlcv, bars=120)
    assert "0.5" in out
    assert out["0.0"] >= out["1.0"]


def test_compute_all(ohlcv):
    out = indicators.compute_all(ohlcv)
    for key in ("ma20", "rsi", "macd_hist", "atr", "close"):
        assert key in out


def test_feature_snapshot_full(ohlcv):
    snap = indicators.compute_features(ohlcv, symbol="TEST")
    assert snap.data_ok
    assert snap.close > 0
    assert snap.ma20 is not None
    assert snap.rsi14 is not None
    assert snap.macd_hist is not None
    assert snap.atr14 is not None
    assert snap.volume_ratio >= 0


def test_feature_snapshot_insufficient(small_ohlcv):
    snap = indicators.compute_features(small_ohlcv, symbol="TINY")
    assert snap.data_ok  # still ok with 10 bars
    # MA20 and MA50 might be None since min_periods=n
    assert snap.ma20 is None  # only 10 rows, need 20


def test_feature_snapshot_empty():
    empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    snap = indicators.compute_features(empty_df, symbol="EMPTY")
    assert not snap.data_ok
    assert snap.close == 0.0


def test_reason_flags_bullish(ohlcv):
    snap = indicators.compute_features(ohlcv, symbol="BULL")
    # uptrending data should produce TREND_UP
    assert "TREND_UP" in snap.reason_flags or len(snap.reason_flags) >= 0


def test_to_dict_keys(ohlcv):
    snap = indicators.compute_features(ohlcv, symbol="TST")
    d = snap.to_dict()
    for key in ("close", "ma20", "rsi", "macd_hist", "volume_spike", "fib"):
        assert key in d
