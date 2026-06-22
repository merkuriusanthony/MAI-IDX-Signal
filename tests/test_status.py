"""Tests for /api/status (Phase 4 Group A)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import VERSION, app

client = TestClient(app)


def test_api_status_ok():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["version"] == VERSION
    assert "scheduler_enabled" in body
    assert "database" in body
    db = body["database"]
    assert "connected" in db
    assert "tables" in db
    # key tables are reported (presence boolean), regardless of value
    for t in ("signals", "scan_runs", "backtest_runs", "users"):
        assert t in db["tables"]


def test_health_endpoints_unchanged():
    for path in ("/health", "/api/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
