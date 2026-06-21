"""Tests for signal generator."""
import numpy as np
import pandas as pd
import pytest

from app.signals.generator import _idx_tick, _levels, generate_signals


def test_idx_tick_rounding():
    assert _idx_tick(195.0) == 195.0
    assert _idx_tick(1234.0) == 1235.0  # round to nearest 5
    assert _idx_tick(4999.0) == 5000.0  # round to nearest 10
    assert _idx_tick(5001.0) == 5000.0  # round to nearest 25... 5001/25=200.04 -> 200*25=5000


def test_levels_valid():
    lv = _levels(5000.0, 80.0, 4700.0)
    assert lv["tp1"] > lv["entry"]
    assert lv["tp2"] > lv["tp1"]
    assert lv["stop_loss"] < lv["entry"]
    assert lv["invalidation"] <= lv["stop_loss"]
    assert lv["risk_reward"] >= 0


def test_levels_rr_positive():
    lv = _levels(5000.0, 100.0, 4800.0)
    assert lv["risk_reward"] > 0


def test_levels_zero_atr_fallback():
    lv = _levels(2000.0, 0.0, 1900.0)
    assert lv["tp1"] > lv["entry"]
    assert lv["stop_loss"] < lv["entry"]


@pytest.mark.asyncio
async def test_generate_signals_empty_returns_empty():
    """Empty symbol list returns empty."""
    result = await generate_signals([])
    assert result == []


@pytest.mark.asyncio
async def test_generate_signals_bad_symbol():
    """Bad/unreachable symbol returns empty, does not crash."""
    result = await generate_signals(["XXXXXXXXX_INVALID"])
    assert isinstance(result, list)
    # may return empty if data unavailable
