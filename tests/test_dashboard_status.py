"""Tests for /dashboard/status ops page (Phase 4 Group C)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import VERSION, app

client = TestClient(app)


def test_dashboard_status_renders():
    r = client.get("/dashboard/status")
    assert r.status_code == 200
    assert "MAI-IDX-Signal" in r.text
    assert VERSION in r.text
    # table status section + key links present
    assert "Tabel Database" in r.text
    assert "/dashboard/backtest" in r.text
    assert "/admin" in r.text
    assert "/api/status" in r.text


def test_dashboard_index_links_to_status():
    r = client.get("/dashboard/")
    assert r.status_code == 200
    assert "/dashboard/status" in r.text
