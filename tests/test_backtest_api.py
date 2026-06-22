"""Tests for the non-blocking backtest API (Phase 4 Group B)."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db import create_backtest_run, finish_backtest_run, init_db
from app.main import app

client = TestClient(app)


def test_trigger_backtest_is_nonblocking():
    # Empty symbol list -> nothing to fetch; returns immediately as queued.
    r = client.post("/api/backtest", json={"symbols": [], "days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert isinstance(body["run_id"], int)


def test_backtest_run_alias():
    r = client.post("/api/backtest/run", json={"symbols": [], "days": 30})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_list_runs_and_detail():
    # Seed a completed run deterministically (no network).
    async def _seed() -> int:
        await init_db()
        rid = await create_backtest_run(strategy="test", universe_size=0)
        await finish_backtest_run(
            rid,
            {"total_signals": 0, "win_rate": 0.0, "avg_return": 0.0, "max_drawdown": 0.0},
        )
        return rid

    rid = asyncio.run(_seed())

    r = client.get("/api/backtest/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(run["id"] == rid for run in body["runs"])

    r = client.get(f"/api/backtest/runs/{rid}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["run"]["id"] == rid
    assert detail["run"]["status"] == "completed"
    assert "results" in detail


def test_run_detail_404():
    r = client.get("/api/backtest/runs/99999999")
    assert r.status_code == 404


def test_dashboard_backtest_does_not_crash():
    r = client.get("/dashboard/backtest")
    assert r.status_code == 200
    assert "Backtest" in r.text
