"""Tests for landing / member / admin pages (Group E)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_landing_root_ok():
    r = client.get("/")
    assert r.status_code == 200
    assert "MAI-IDX-Signal" in r.text
    assert "963" in r.text


def test_member_requires_tg_id():
    r = client.get("/member")
    assert r.status_code == 200
    assert "Telegram" in r.text


def test_admin_rejects_bad_key():
    r = client.get("/admin?key=definitely-wrong-key")
    assert r.status_code == 403
