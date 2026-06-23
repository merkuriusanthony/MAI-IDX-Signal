"""Tests for Feature 1: swarm full-universe worker-pool scanning.

Mocks all network/blocking fetches — never hits yfinance.
"""
from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _fake_regime():
    from app.analytics.regime import MarketRegime
    return MarketRegime(
        regime="neutral", above_ma50=True, above_ma200=True,
        vol_annual=0.2, index_close=7000.0, ok=True, reason="test",
    )


def _fake_df(rows: int = 120) -> pd.DataFrame:
    """Deterministic upward-drifting OHLCV frame with enough history."""
    idx = pd.date_range("2024-01-01", periods=rows, freq="D")
    base = np.linspace(1000, 1500, rows)
    df = pd.DataFrame(
        {
            "open": base,
            "high": base * 1.02,
            "low": base * 0.98,
            "close": base,
            "volume": np.full(rows, 5_000_000),
        },
        index=idx,
    )
    df.attrs["symbol"] = "TEST"
    return df


@pytest.fixture()
def scanner_env(tmp_path, monkeypatch):
    """Temp DB + small universe file + mocked fetch/regime."""
    db_path = tmp_path / "scan.db"
    uni_path = tmp_path / "uni.txt"
    symbols = [f"SYM{i:03d}" for i in range(50)]
    uni_path.write_text("\n".join(symbols) + "\n")

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("IDX_UNIVERSE_PATH", str(uni_path))
    monkeypatch.setenv("SCAN_CHECKPOINT_INTERVAL", "10")
    monkeypatch.setenv("SCAN_CONCURRENCY", "8")
    monkeypatch.setenv("SCAN_MIN_AVG_VALUE", "0")

    import app.config as cfg
    import app.db as dbm
    import app.data.universe as uni_mod
    import app.scanner as scanner_mod
    importlib.reload(cfg)
    importlib.reload(dbm)
    # universe + scanner hold their own `settings` / load_universe refs; reload
    # so they see the temp universe path under any full-suite import ordering.
    importlib.reload(uni_mod)
    importlib.reload(scanner_mod)

    return symbols, db_path


@pytest.mark.asyncio
async def test_worker_pool_scans_all_symbols(scanner_env, monkeypatch):
    symbols, _ = scanner_env
    import app.db as dbm
    await dbm.init_db()

    fetched = []

    def fake_fetch(symbol, *a, **k):
        fetched.append(symbol)
        df = _fake_df()
        df.attrs["symbol"] = symbol
        return {
            "symbol": symbol, "df": df, "ok": True, "error": None,
            "close": 1500.0, "avg_volume_20": 5_000_000.0,
            "value_estimate": 1500.0 * 5_000_000,
        }

    # Patch where scanner imported the symbols.
    import app.scanner as scanner_mod
    importlib.reload(scanner_mod)
    monkeypatch.setattr(scanner_mod, "fetch_ohlcv_safe", fake_fetch)

    monkeypatch.setattr(scanner_mod, "detect_regime", lambda *a, **k: _fake_regime())

    sc = scanner_mod.ScannerService(mode="manual", generate_charts=False)
    result = await sc.run()

    assert result["status"] == "success"
    assert result["scanned"] == len(symbols)
    # every symbol pulled from the queue exactly once
    assert sorted(fetched) == sorted(symbols)


@pytest.mark.asyncio
async def test_limit_none_covers_full_universe(scanner_env, monkeypatch):
    symbols, _ = scanner_env
    import app.scanner as scanner_mod
    importlib.reload(scanner_mod)

    sc = scanner_mod.ScannerService(mode="manual", limit=None)
    # universe attribute should equal the full file contents
    assert len(sc.universe) == len(symbols)


@pytest.mark.asyncio
async def test_progress_is_checkpointed(scanner_env, monkeypatch):
    symbols, _ = scanner_env
    import app.db as dbm
    await dbm.init_db()

    import app.scanner as scanner_mod
    importlib.reload(scanner_mod)

    def fake_fetch(symbol, *a, **k):
        df = _fake_df()
        df.attrs["symbol"] = symbol
        return {
            "symbol": symbol, "df": df, "ok": True, "error": None,
            "close": 1500.0, "avg_volume_20": 5_000_000.0,
            "value_estimate": 1500.0 * 5_000_000,
        }
    monkeypatch.setattr(scanner_mod, "fetch_ohlcv_safe", fake_fetch)

    monkeypatch.setattr(scanner_mod, "detect_regime", lambda *a, **k: _fake_regime())

    # Spy on the checkpoint helper.
    calls = []
    orig = scanner_mod.update_scan_progress

    async def spy(run_id, scanned):
        calls.append(scanned)
        await orig(run_id, scanned)
    monkeypatch.setattr(scanner_mod, "update_scan_progress", spy)

    sc = scanner_mod.ScannerService(mode="manual", generate_charts=False)
    result = await sc.run()

    # checkpoint interval=10, 50 symbols -> at least 5 checkpoints
    assert len(calls) >= 5
    assert max(calls) <= len(symbols)

    # final scanned_count persisted on the ScanRun row
    from sqlalchemy import select
    async with dbm.async_session() as db:
        run = (await db.execute(
            select(dbm.ScanRun).where(dbm.ScanRun.id == result["scan_run_id"])
        )).scalar_one()
        assert run.scanned_count == len(symbols)


@pytest.mark.asyncio
async def test_fetch_failures_counted_not_fatal(scanner_env, monkeypatch):
    symbols, _ = scanner_env
    import app.db as dbm
    await dbm.init_db()

    import app.scanner as scanner_mod
    importlib.reload(scanner_mod)

    def fake_fetch(symbol, *a, **k):
        return {"symbol": symbol, "df": None, "ok": False, "error": "no data",
                "close": None, "avg_volume_20": 0.0, "value_estimate": 0.0}
    monkeypatch.setattr(scanner_mod, "fetch_ohlcv_safe", fake_fetch)

    monkeypatch.setattr(scanner_mod, "detect_regime", lambda *a, **k: _fake_regime())

    sc = scanner_mod.ScannerService(mode="manual", generate_charts=False)
    result = await sc.run()
    assert result["status"] == "success"
    assert result["scanned"] == len(symbols)
    assert result["failed"] == len(symbols)
    assert result["passed"] == 0
