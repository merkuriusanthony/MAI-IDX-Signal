"""Tests for database helpers."""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Fixture: temp SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    # reset cached settings and engine
    import importlib
    import app.config as cfg_module
    import app.db as db_module
    importlib.reload(cfg_module)
    importlib.reload(db_module)
    yield
    # cleanup handled by tmp_path


@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    await db_mod.init_db()
    assert db_path.exists()


@pytest.mark.asyncio
async def test_create_and_finish_scan_run(tmp_path, monkeypatch):
    db_path = tmp_path / "t2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    run_id = await db_mod.create_scan_run("manual", 100)
    assert isinstance(run_id, int) and run_id > 0

    await db_mod.finish_scan_run(run_id, "success", scanned=80, passed=5, failed=3)

    from sqlalchemy import select
    async with db_mod.async_session() as db:
        result = await db.execute(select(db_mod.ScanRun).where(db_mod.ScanRun.id == run_id))
        run = result.scalar_one()
        assert run.status == "success"
        assert run.scanned_count == 80


@pytest.mark.asyncio
async def test_reap_stale_scan_runs(tmp_path, monkeypatch):
    db_path = tmp_path / "t2reap.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    from datetime import timedelta
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    from sqlalchemy import select

    # Stale run: started >30min ago, still 'running'
    stale_id = await db_mod.create_scan_run("eod", 655)
    # Fresh run: started just now, still 'running' (must survive)
    fresh_id = await db_mod.create_scan_run("manual", 5)
    async with db_mod.async_session() as db:
        res = await db.execute(select(db_mod.ScanRun).where(db_mod.ScanRun.id == stale_id))
        run = res.scalar_one()
        run.started_at = (db_mod._utcnow() - timedelta(hours=2)).isoformat()
        await db.commit()

    reaped = await db_mod.reap_stale_scan_runs(max_age_minutes=30)
    assert reaped == 1

    async with db_mod.async_session() as db:
        res = await db.execute(select(db_mod.ScanRun).where(db_mod.ScanRun.id == stale_id))
        stale = res.scalar_one()
        assert stale.status == "failed"
        assert stale.finished_at is not None
        assert "reaped" in (stale.error or "")

        res = await db.execute(select(db_mod.ScanRun).where(db_mod.ScanRun.id == fresh_id))
        fresh = res.scalar_one()
        assert fresh.status == "running"


@pytest.mark.asyncio
async def test_save_and_list_signals(tmp_path, monkeypatch):
    db_path = tmp_path / "t3.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    sig_id = await db_mod.save_signal_dict({
        "symbol": "BBRI",
        "action": "BUY",
        "entry": 5000.0,
        "tp1": 5500.0,
        "tp2": 6000.0,
        "stop_loss": 4700.0,
        "confidence": 0.75,
        "score": 80.0,
        "reasons": ["TREND_UP", "VOLUME_SPIKE"],
    })
    assert sig_id > 0

    signals = await db_mod.list_latest_signals()
    assert len(signals) == 1
    assert signals[0]["symbol"] == "BBRI"
    assert signals[0]["action"] == "BUY"


@pytest.mark.asyncio
async def test_save_ohlcv_and_load(tmp_path, monkeypatch):
    db_path = tmp_path / "t4.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    rows = [
        {"date": "2024-01-01", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1_000_000},
        {"date": "2024-01-02", "open": 105, "high": 115, "low": 100, "close": 112, "volume": 1_200_000},
    ]
    await db_mod.save_ohlcv("BBRI", rows, source="yahoo")

    loaded = await db_mod.load_ohlcv("BBRI", "2024-01-01", "2024-01-31")
    assert len(loaded) == 2
    assert loaded[0]["close"] == 105.0


@pytest.mark.asyncio
async def test_save_scan_candidate(tmp_path, monkeypatch):
    db_path = tmp_path / "t5.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    run_id = await db_mod.create_scan_run("manual", 10)
    cand_id = await db_mod.save_scan_candidate(run_id, {
        "symbol": "ANTM",
        "score": 70.5,
        "action": "WATCH",
        "close": 2000.0,
        "volume": 500_000_000,
        "value_estimate": 1_000_000_000,
        "rsi": 58.0,
        "ma20": 1950.0,
        "ma50": 1900.0,
        "volume_ratio": 1.5,
    })
    assert cand_id > 0


@pytest.mark.asyncio
async def test_update_signal_status(tmp_path, monkeypatch):
    db_path = tmp_path / "t6.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import importlib
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    await db_mod.init_db()

    sig_id = await db_mod.save_signal_dict({
        "symbol": "TLKM",
        "action": "BUY",
        "entry": 3000.0,
        "tp1": 3300.0,
        "tp2": 3600.0,
        "stop_loss": 2800.0,
        "confidence": 0.7,
        "score": 77.0,
    })

    await db_mod.update_signal_status(sig_id, {
        "last_price": 3350.0,
        "max_price": 3350.0,
        "min_price": 3000.0,
        "status": "tp1",
        "return_pct": 11.67,
        "holding_days": 5,
    })

    sigs = await db_mod.list_latest_signals()
    assert sigs[0]["status"] == "tp1"
