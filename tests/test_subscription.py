"""Tests for subscription access control (Group D)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def test_access_control_unknown_user_allowed():
    from app.subscription.access import can_receive_signal

    with patch("app.db.get_user_by_telegram_id", new=AsyncMock(return_value=None)):
        allowed, reason = asyncio.run(can_receive_signal(123))
    assert allowed is True
    assert reason == ""


def test_access_control_free_limit_blocks():
    from app.subscription.access import can_receive_signal, FREE_DAILY_LIMIT

    user = SimpleNamespace(tier="free", signal_count=FREE_DAILY_LIMIT)
    with patch("app.db.get_user_by_telegram_id", new=AsyncMock(return_value=user)):
        allowed, reason = asyncio.run(can_receive_signal(123))
    assert allowed is False
    assert "Pro" in reason


def test_access_control_pro_unlimited():
    from app.subscription.access import can_receive_signal

    user = SimpleNamespace(tier="pro", signal_count=999)
    with patch("app.db.get_user_by_telegram_id", new=AsyncMock(return_value=user)):
        allowed, reason = asyncio.run(can_receive_signal(123))
    assert allowed is True
