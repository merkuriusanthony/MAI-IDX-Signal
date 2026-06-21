"""Tests for the scoring engine."""
import numpy as np
import pandas as pd
import pytest

from app.analytics.scoring import VALID_LABELS, score


@pytest.fixture
def df():
    n = 60
    close = np.linspace(100, 130, n)
    return pd.DataFrame(
        {
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": np.linspace(1000, 2000, n),
        }
    )


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
        ma20=85.0,
        ma50=90.0,
        ma200=100.0,
        rsi=25.0,
        macd_hist=-1.0,
        volume_spike={"latest": 500, "avg": 1000, "ratio": 0.5},
    )
    out = score(df, ind)
    assert out["label"] in {"AVOID", "DANGER", "HOLD"}
    assert out["score"] < 60


def test_reasons_not_empty(df):
    out = score(df, _indicators(130.0))
    assert len(out["reasons"]) > 0
