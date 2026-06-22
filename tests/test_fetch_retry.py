"""Tests for the Yahoo fetch retry guard (Group A)."""
from __future__ import annotations


def test_fetch_retry_on_empty():
    from app.data.fetch_yahoo import fetch_ohlcv_safe

    r = fetch_ohlcv_safe("XXXX_NOT_REAL")
    assert r["ok"] is False
