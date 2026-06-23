"""Tests for Feature 2: daily universe auto-update (IPO/delisting).

All network fetchers are mocked — never hits IDX/Stockbit/Yahoo.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture()
def uni_env(tmp_path, monkeypatch):
    """Universe file + isolated backup/changelog dirs."""
    uni = tmp_path / "idx_universe.txt"
    # 100 current symbols AAA0..  -> easy ratio math
    current = [f"AA{i:02d}" for i in range(100)]
    uni.write_text("\n".join(current) + "\n")

    backup_dir = tmp_path / "backups"
    changelog = tmp_path / "changes.jsonl"

    monkeypatch.setenv("IDX_UNIVERSE_PATH", str(uni))
    monkeypatch.setenv("UNIVERSE_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("UNIVERSE_CHANGES_LOG", str(changelog))
    monkeypatch.setenv("UNIVERSE_MIN_RATIO", "0.80")

    import app.config as cfg
    importlib.reload(cfg)
    import app.data.universe as uni_mod
    importlib.reload(uni_mod)
    import app.data.universe_update as upd
    importlib.reload(upd)

    return upd, uni, current, backup_dir, changelog


def test_normalize_strips_jk_and_junk(uni_env):
    upd, *_ = uni_env
    out = upd._normalize(["bbca", "BBRI.JK", "  TLKM ", "x", "TOOLONG", "bbca", " AB12 "])
    assert out == ["AB12", "BBCA", "BBRI", "TLKM"]


def test_diff_added_removed(uni_env):
    upd, *_ = uni_env
    added, removed = upd.diff_universe(["AAA0", "BBB0"], ["BBB0", "CCC0"])
    assert added == ["CCC0"]
    assert removed == ["AAA0"]


def test_update_applies_changes_with_backup_and_log(uni_env):
    upd, uni, current, backup_dir, changelog = uni_env
    # drop one (delist), add one (IPO)
    new = current[1:] + ["ZZZZ"]
    result = upd.update_universe_file(new_symbols=new)

    assert result["status"] == "updated"
    assert result["added"] == ["ZZZZ"]
    assert result["removed"] == ["AA00"]

    # file rewritten (sorted), no .JK
    written = uni.read_text().split()
    assert "ZZZZ" in written
    assert "AA00" not in written
    assert written == sorted(written)

    # backup created with old content
    backups = os.listdir(backup_dir)
    assert len(backups) == 1
    assert "AA00" in (backup_dir / backups[0]).read_text()

    # change-history JSONL appended
    entry = json.loads(changelog.read_text().strip())
    assert entry["added"] == ["ZZZZ"]
    assert entry["removed"] == ["AA00"]


def test_no_change_does_not_write_backup(uni_env):
    upd, uni, current, backup_dir, changelog = uni_env
    result = upd.update_universe_file(new_symbols=list(current))
    assert result["status"] == "no_change"
    assert not backup_dir.exists() or os.listdir(backup_dir) == []
    assert not changelog.exists()


def test_sanity_gate_aborts_on_too_small(uni_env):
    upd, uni, current, backup_dir, _ = uni_env
    before = uni.read_text()
    # only 50 of 100 -> below 80% gate
    result = upd.update_universe_file(new_symbols=current[:50])
    assert result["status"] == "aborted"
    assert "too small" in result["error"]
    # file untouched
    assert uni.read_text() == before


def test_sanity_gate_aborts_on_empty(uni_env):
    upd, uni, *_ = uni_env
    before = uni.read_text()
    result = upd.update_universe_file(new_symbols=[])
    assert result["status"] == "error"
    assert uni.read_text() == before


def test_atomic_write_no_tmp_leftover(uni_env):
    upd, uni, current, *_ = uni_env
    new = current[5:] + ["WXYZ", "ABCD"]
    upd.update_universe_file(new_symbols=new)
    parent = os.path.dirname(str(uni))
    leftovers = [f for f in os.listdir(parent) if f.endswith(".tmp")]
    assert leftovers == []


def test_fetch_fallback_order(uni_env, monkeypatch):
    upd, *_ = uni_env
    # idx fails, stockbit empty (auth-skip), yahoo wins
    monkeypatch.setattr(upd, "_fetch_idx", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(upd, "_fetch_stockbit", lambda: [])
    monkeypatch.setattr(upd, "_fetch_yahoo", lambda: ["BBCA", "BBRI"])
    syms, source = upd.fetch_current_symbols()
    assert source == "yahoo"
    assert syms == ["BBCA", "BBRI"]


def test_fetch_idx_wins_first(uni_env, monkeypatch):
    upd, *_ = uni_env
    monkeypatch.setattr(upd, "_fetch_idx", lambda: ["TLKM", "ASII"])
    monkeypatch.setattr(upd, "_fetch_stockbit", lambda: ["SHOULD_NOT"])
    syms, source = upd.fetch_current_symbols()
    assert source == "idx"
    assert syms == ["TLKM", "ASII"]


@pytest.mark.asyncio
async def test_scheduler_job_notifies_on_change(uni_env, monkeypatch):
    upd, uni, current, *_ = uni_env
    import app.scheduler.jobs as jobs
    importlib.reload(jobs)

    new = current[1:] + ["ZZZZ"]
    monkeypatch.setattr(
        "app.data.universe_update.fetch_current_symbols",
        lambda: (new, "idx"),
    )

    sent = {}

    async def fake_notify(text, chat_id=None):
        sent["text"] = text
        return True
    monkeypatch.setattr("app.bots.telegram.send_text_notify", fake_notify)

    await jobs.universe_update_job()
    assert "text" in sent
    assert "ZZZZ" in sent["text"]
    assert "AA00" in sent["text"]


@pytest.mark.asyncio
async def test_scheduler_job_quiet_on_no_change(uni_env, monkeypatch):
    upd, uni, current, *_ = uni_env
    import app.scheduler.jobs as jobs
    importlib.reload(jobs)

    monkeypatch.setattr(
        "app.data.universe_update.fetch_current_symbols",
        lambda: (list(current), "idx"),
    )

    sent = {}

    async def fake_notify(text, chat_id=None):
        sent["text"] = text
        return True
    monkeypatch.setattr("app.bots.telegram.send_text_notify", fake_notify)

    await jobs.universe_update_job()
    assert "text" not in sent  # no notification when nothing changed


@pytest.mark.asyncio
async def test_scheduler_job_disabled(uni_env, monkeypatch):
    monkeypatch.setenv("UNIVERSE_AUTOUPDATE_ENABLED", "false")
    import app.config as cfg
    importlib.reload(cfg)
    import app.scheduler.jobs as jobs
    importlib.reload(jobs)

    called = {"fetch": False}
    monkeypatch.setattr(
        "app.data.universe_update.fetch_current_symbols",
        lambda: (called.__setitem__("fetch", True), ([], "none"))[1],
    )
    await jobs.universe_update_job()
    assert called["fetch"] is False
