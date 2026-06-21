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


def test_ma_shape(ohlcv):
    out = indicators.ma(ohlcv, 20)
    assert len(out) == len(ohlcv)
    assert not out.isna().all()


def test_rsi_range(ohlcv):
    out = indicators.rsi(ohlcv)
    assert len(out) == len(ohlcv)
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
