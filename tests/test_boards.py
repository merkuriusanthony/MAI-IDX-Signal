"""Tests for RG/NG/TN board classification (Group B)."""
from __future__ import annotations


def test_get_board_rg():
    from app.data.boards import get_board

    assert get_board("BBCA") == "RG"


def test_get_board_ng():
    from app.data.boards import get_board

    assert get_board("DNAR") == "NG"


def test_get_profile_includes_board():
    from app.data.sectors import get_profile

    profile = get_profile("BBCA")
    assert profile.get("board") == "RG"
    # ensure existing sector data preserved
    assert profile.get("sector") == "Financial Services"
