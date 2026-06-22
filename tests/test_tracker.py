"""Tests for the signal tracker (PnL + TP/SL/EXPIRED detection)."""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


def _reload_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tracker.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    import app.config as cfg_mod
    import app.db as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)
    import app.signals.tracker as tracker_mod
    importlib.reload(tracker_mod)
    return db_mod, tracker_mod


def _fake_df(close, high=None, low=None):
    high = high if high is not None else close
    low = low if low is not None else close
    return pd.DataFrame({"close": [close], "high": [high], "low": [low]})


@pytest.mark.asyncio
async def test_tracker_marks_tp1(tmp_path, monkeypatch):
    db_mod, tracker_mod = _reload_db(tmp_path, monkeypatch)
    await db_mod.init_db()
    sig_id = await db_mod.save_signal_dict({
        "symbol": "BBCA", "action": "BUY", "entry": 1000.0,
        "tp1": 1100.0, "tp2": 1200.0, "stop_loss": 900.0, "score": 80.0,
    })

    monkeypatch.setattr(
        "app.data.fetch_yahoo.fetch_ohlcv",
        lambda symbol, period="5d": _fake_df(1150.0),
    )
    result = await tracker_mod.update_all_open_signals()
    assert result["updated"] == 1

    sigs = await db_mod.list_latest_signals()
    assert sigs[0]["status"] == "tp1"
    assert sig_id > 0


@pytest.mark.asyncio
async def test_tracker_marks_sl(tmp_path, monkeypatch):
    db_mod, tracker_mod = _reload_db(tmp_path, monkeypatch)
    await db_mod.init_db()
    await db_mod.save_signal_dict({
        "symbol": "BBRI", "action": "BUY", "entry": 1000.0,
        "tp1": 1100.0, "tp2": 1200.0, "stop_loss": 900.0, "score": 70.0,
    })
    monkeypatch.setattr(
        "app.data.fetch_yahoo.fetch_ohlcv",
        lambda symbol, period="5d": _fake_df(850.0),
    )
    await tracker_mod.update_all_open_signals()
    sigs = await db_mod.list_latest_signals()
    assert sigs[0]["status"] == "stopped"


@pytest.mark.asyncio
async def test_tracker_marks_expired(tmp_path, monkeypatch):
    db_mod, tracker_mod = _reload_db(tmp_path, monkeypatch)
    await db_mod.init_db()
    sig_id = await db_mod.save_signal_dict({
        "symbol": "TLKM", "action": "BUY", "entry": 1000.0,
        "tp1": 1100.0, "tp2": 1200.0, "stop_loss": 900.0, "score": 65.0,
    })
    # backdate created_at > 20 days
    from sqlalchemy import select
    async with db_mod.async_session() as db:
        res = await db.execute(select(db_mod.Signal).where(db_mod.Signal.id == sig_id))
        sig = res.scalar_one()
        sig.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=25)
        await db.commit()

    monkeypatch.setattr(
        "app.data.fetch_yahoo.fetch_ohlcv",
        lambda symbol, period="5d": _fake_df(1050.0),  # between entry and tp1
    )
    await tracker_mod.update_all_open_signals()
    sigs = await db_mod.list_latest_signals()
    assert sigs[0]["status"] == "expired"


@pytest.mark.asyncio
async def test_tracker_stays_open(tmp_path, monkeypatch):
    db_mod, tracker_mod = _reload_db(tmp_path, monkeypatch)
    await db_mod.init_db()
    await db_mod.save_signal_dict({
        "symbol": "ADRO", "action": "BUY", "entry": 1000.0,
        "tp1": 1100.0, "tp2": 1200.0, "stop_loss": 900.0, "score": 60.0,
    })
    monkeypatch.setattr(
        "app.data.fetch_yahoo.fetch_ohlcv",
        lambda symbol, period="5d": _fake_df(1020.0),
    )
    await tracker_mod.update_all_open_signals()
    sigs = await db_mod.list_latest_signals()
    assert sigs[0]["status"] == "open"
