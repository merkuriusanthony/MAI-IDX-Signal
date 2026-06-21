"""Minimal smoke tests for the dashboard router."""
from __future__ import annotations


def test_dashboard_router_imports():
    from app.dashboard.routes import router
    paths = {r.path for r in router.routes}
    assert "/dashboard/" in paths
    assert "/dashboard/performance" in paths
    assert "/dashboard/sectors" in paths
    assert "/dashboard/scan" in paths


def test_bar_helper():
    from app.dashboard.routes import _bar
    html = _bar("Win", 42.0)
    assert "42.0%" in html
    assert "width:42%" in html


def test_bar_caps_at_100():
    from app.dashboard.routes import _bar
    html = _bar("Over", 150.0)
    assert "width:100%" in html


def test_get_sector():
    from app.data.sectors import get_sector
    assert get_sector("BBCA") == "Perbankan"
    assert get_sector("bbri") == "Perbankan"
    assert get_sector("UNKNOWN") == "Lainnya"
