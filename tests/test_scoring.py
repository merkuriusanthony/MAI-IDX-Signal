"""Tests for the scoring engine."""
import numpy as np
import pandas as pd
import pytest

from app.analytics.indicators import FeatureSnapshot, compute_features
from app.analytics.scoring import VALID_LABELS, score, score_snapshot


@pytest.fixture
def df():
    n = 60
    close = np.linspace(100, 130, n)
    return pd.DataFrame({
        "open": close - 1, "high": close + 1,
        "low": close - 2, "close": close,
        "volume": np.linspace(1000, 2000, n),
    })


def _indicators(close, **over):
    base = {
        "close": close,
        "ma20": close * 0.98,
        "ma50": close * 0.95,
        "ma200": close * 0.90,
        "rsi": 60.0,
        "macd_hist": 1.0,
        "stoch_k": 50.0,
        "volume_spike": {"latest": 2000, "avg": 1000, "ratio": 2.0},
    }
    base.update(over)
    return base


def test_score_range_and_label(df):
    out = score(df, _indicators(130.0))
    assert 0 <= out["score"] <= 100
    assert out["label"] in VALID_LABELS
    assert isinstance(out["reasons"], list)


def test_strong_uptrend_is_bullish(df):
    out = score(df, _indicators(130.0))
    assert out["label"] in {"BUY", "WATCH"}


def test_bearish_below_ma200(df):
    ind = _indicators(
        80.0,
        ma20=85.0, ma50=90.0, ma200=100.0,
        rsi=25.0, macd_hist=-1.0,
        volume_spike={"latest": 500, "avg": 1000, "ratio": 0.5},
    )
    out = score(df, ind)
    assert out["label"] in {"AVOID", "DANGER", "HOLD"}
    assert out["score"] < 60


def test_reasons_not_empty(df):
    out = score(df, _indicators(130.0))
    assert len(out["reasons"]) > 0


def test_reason_codes_present(df):
    out = score(df, _indicators(130.0))
    assert "reason_codes" in out
    assert isinstance(out["reason_codes"], list)


def test_score_snapshot_bullish():
    snap = FeatureSnapshot(
        symbol="BULL",
        close=5000.0,
        ma5=4950.0, ma20=4800.0, ma50=4500.0, ma100=4300.0, ma200=4000.0,
        rsi14=62.0,
        macd_hist=10.0,
        stoch_k=55.0,
        volume_latest=5_000_000, volume_avg20=3_000_000, volume_ratio=1.67,
        atr14=80.0, atr_pct=1.6,
        support=4700.0, resistance=5200.0,
        data_ok=True, bars_available=250,
    )
    result = score_snapshot(snap)
    assert result["action"] in {"BUY", "WATCH"}
    assert result["score"] >= 60


def test_score_snapshot_bearish():
    snap = FeatureSnapshot(
        symbol="BEAR",
        close=3000.0,
        ma5=3200.0, ma20=3400.0, ma50=3600.0, ma100=3800.0, ma200=4000.0,
        rsi14=25.0,
        macd_hist=-20.0,
        stoch_k=15.0,
        volume_latest=500_000, volume_avg20=2_000_000, volume_ratio=0.25,
        atr14=150.0, atr_pct=5.0,
        support=2800.0, resistance=3500.0,
        breakdown_20d=True,
        data_ok=True, bars_available=120,
    )
    result = score_snapshot(snap)
    assert result["action"] in {"AVOID", "DANGER"}
    assert result["score"] < 45


def test_score_snapshot_no_data():
    snap = FeatureSnapshot(data_ok=False)
    result = score_snapshot(snap)
    assert result["action"] == "DANGER"
    assert result["score"] == 0.0


def test_label_matches_action(df):
    out = score(df, _indicators(130.0))
    assert out["label"] == out["action"]
