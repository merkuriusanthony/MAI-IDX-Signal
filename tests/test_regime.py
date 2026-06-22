"""Tests for the Phase 5.2 market-regime gate."""
import app.analytics.regime as regime_mod
from app.analytics.regime import (
    MarketRegime,
    apply_regime_gate,
    _classify,
)


def _mk(regime="risk_on", ok=True):
    return MarketRegime(
        regime=regime, above_ma50=True, above_ma200=True,
        vol_annual=0.15, index_close=7000.0, ok=ok, reason="t",
    )


# --- classification -------------------------------------------------------

def test_classify_risk_on():
    r = _classify(above_ma50=True, above_ma200=True, vol_annual=0.15, index_close=7000)
    assert r.regime == "risk_on"
    assert not r.risk_off


def test_classify_risk_off_below_ma200():
    r = _classify(above_ma50=True, above_ma200=False, vol_annual=0.15, index_close=6000)
    assert r.regime == "risk_off"
    assert r.risk_off


def test_classify_risk_off_high_vol_below_ma50():
    r = _classify(above_ma50=False, above_ma200=True, vol_annual=0.40, index_close=6500)
    assert r.regime == "risk_off"


def test_classify_neutral_high_vol_but_uptrend():
    # high vol but still above both MAs -> neutral, not risk_off
    r = _classify(above_ma50=True, above_ma200=True, vol_annual=0.40, index_close=7000)
    assert r.regime == "neutral"
    assert not r.risk_off


# --- gate -----------------------------------------------------------------

def test_gate_downgrades_buy_when_risk_off():
    action, gated, note = apply_regime_gate("BUY", _mk("risk_off"))
    assert action == "WATCH"
    assert gated is True
    assert "risk-off" in note.lower()


def test_gate_leaves_watch_untouched():
    action, gated, _ = apply_regime_gate("WATCH", _mk("risk_off"))
    assert action == "WATCH"
    assert gated is False


def test_gate_noop_when_risk_on():
    action, gated, _ = apply_regime_gate("BUY", _mk("risk_on"))
    assert action == "BUY"
    assert gated is False


def test_gate_fails_open_when_regime_unavailable():
    # ok=False (index data missing) must NOT change actions
    action, gated, _ = apply_regime_gate("BUY", _mk("risk_off", ok=False))
    assert action == "BUY"
    assert gated is False


# --- detect_regime fail-open ---------------------------------------------

def test_detect_regime_fails_open_on_empty(monkeypatch):
    import pandas as pd

    def fake_fetch(*a, **k):
        return pd.DataFrame()

    monkeypatch.setattr("app.data.fetch_yahoo.fetch_ohlcv", fake_fetch)
    regime_mod._cache = None  # bypass cache
    r = regime_mod.detect_regime(use_cache=False)
    assert r.ok is False
    assert r.regime == "neutral"
    # fail-open must not gate
    action, gated, _ = apply_regime_gate("BUY", r)
    assert action == "BUY" and gated is False


def test_detect_regime_classifies_uptrend(monkeypatch):
    import numpy as np
    import pandas as pd

    # 250 bars rising steadily -> close above MA50 & MA200, low vol
    close = np.linspace(5000, 7500, 250)
    df = pd.DataFrame({
        "open": close, "high": close + 5, "low": close - 5,
        "close": close, "volume": np.full(250, 1e6),
    })

    monkeypatch.setattr("app.data.fetch_yahoo.fetch_ohlcv", lambda *a, **k: df)
    regime_mod._cache = None
    r = regime_mod.detect_regime(use_cache=False)
    assert r.ok is True
    assert r.above_ma50 and r.above_ma200
    assert r.regime in {"risk_on", "neutral"}
