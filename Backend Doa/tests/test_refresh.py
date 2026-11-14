# tests/test_refresh.py
"""features/sync/refresh.py: the unattended job (backup, sync, identity, index, check).

No network, no model, no real database: the steps are fakes and the database is the test one."""

import json
import os
import sqlite3
import time

import pytest

import db.schema as schema
import features.sync.refresh as refresh_module
from features.sync.refresh import (acquire_lock, backup_database, main, refresh, sync_until_complete,
                                   table_counts)
from tests.helpers import add_post, add_proposal


def status(votes_ok=True, forum_ok=True, proposals=1, votes=10, posts=5):
    """An audit result with only the keys the refresh reads."""
    return {"total_proposals": proposals,
            "votes": {"total_votes": votes, "completeness": {
                "complete": proposals if votes_ok else 0, "is_complete": votes_ok,
                "incomplete_proposals": [] if votes_ok else [{"proposal_id": "P"}]}},
            "forum": {"total_posts": posts, "completeness": {
                "complete": 1 if forum_ok else 0, "is_complete": forum_ok,
                "incomplete_threads": [] if forum_ok else [{"url": "u", "status": "error"}]}}}


def fake_steps(calls, sync_status=None, **overrides):
    """Steps that record the order they ran in."""
    sync_status = sync_status or status()

    def step(name, result):
        def run(*args, **kwargs):
            calls.append(name)
            return result
        return run
    steps = {"sync_all": step("sync", {"current_status": sync_status}),
             "audit": lambda conn: sync_status,
             "rescore": step("identity", {"steps": ["long"], "stats": {"linked": 3}}),
             "sync_index": step("index", {"documents": 2, "embed": 1, "foreign": 0}),
             "check_index": step("check", {"total": 2, "valid": 2, "invalid": 0, "legacy": 0, "foreign": 0})}
    steps.update(overrides)
    return steps


def boom(*args, **kwargs):
    raise RuntimeError("network down")


# ── backup ────────────────────────────────────────────────────────────────────

def test_the_backup_is_a_healthy_copy_with_the_same_rows(db, tmp_path):
    add_proposal(db, "P")
    add_post(db, 1, "P", "ann", "hello")
    db.commit()
    copy = backup_database(schema.DB_PATH, tmp_path / "backups")
    conn = sqlite3.connect(copy)
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0] == 1
    conn.close()
    db.execute("DELETE FROM proposals")                         # the original changes ...
    db.commit()
    conn = sqlite3.connect(copy)
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1     # ... the backup does not
    conn.close()


def test_only_the_newest_backups_are_kept(db, tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for day in ("20260101", "20260102", "20260103"):
        (folder / f"dao_intelligence_{day}_000000.db").write_text("old")
    (folder / "notes.txt").write_text("not a backup")
    newest = backup_database(schema.DB_PATH, folder, keep=2)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["dao_intelligence_20260103_000000.db", newest.name, "notes.txt"]


# ── one run at a time ─────────────────────────────────────────────────────────

def test_a_second_run_is_refused_and_a_dead_runs_lock_is_taken_over(tmp_path):
    lock = acquire_lock(tmp_path)
    assert lock is not None and acquire_lock(tmp_path) is None
    old = time.time() - 10_000
    os.utime(lock, (old, old))
    assert acquire_lock(tmp_path, stale_after=3_600) is not None         # older than an hour: the run died


def test_main_does_nothing_while_another_refresh_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(refresh_module, "refresh", boom)                 # would fail the test if it ran
    acquire_lock(tmp_path)
    assert main([], log_dir=tmp_path) == 2
    assert "Another refresh is running" in capsys.readouterr().out


# ── the sync loop ─────────────────────────────────────────────────────────────

def looping_sync(statuses):
    """A sync_all that returns the next status each round, and how many rounds ran."""
    rounds = []

    def sync_all(conn, votes_proposals_limit):
        rounds.append(votes_proposals_limit)
        return {"current_status": statuses[min(len(rounds), len(statuses)) - 1]}
    return sync_all, rounds


def test_the_sync_stops_as_soon_as_everything_is_complete():
    sync_all, rounds = looping_sync([status(votes_ok=False, votes=10), status(votes=20)])
    out = sync_until_complete(None, sync_all, lambda conn: status(votes_ok=False, votes=5))
    assert (out["rounds"], out["stopped_because"], out["votes_complete"]) == (2, "complete", True)
    assert len(rounds) == 2


def test_the_sync_stops_when_a_round_brings_nothing_new():
    """A deleted forum thread never completes: without this rule every run would use all its rounds."""
    stuck = status(forum_ok=False)
    sync_all, rounds = looping_sync([stuck])
    out = sync_until_complete(None, sync_all, lambda conn: stuck)
    assert (out["rounds"], out["stopped_because"], out["forum_complete"]) == (1, "nothing_new", False)
    assert out["incomplete"]["threads"] == [{"url": "u", "status": "error"}]


def test_the_sync_gives_up_after_max_rounds_while_still_making_progress():
    growing = [status(votes_ok=False, votes=n) for n in (10, 20, 30, 40, 50)]
    sync_all, rounds = looping_sync(growing)
    out = sync_until_complete(None, sync_all, lambda conn: status(votes_ok=False, votes=0), max_rounds=3)
    assert (out["rounds"], out["stopped_because"]) == (3, "max_rounds") and len(rounds) == 3


# ── the whole job ─────────────────────────────────────────────────────────────

def test_a_good_run_does_every_step_in_order(db, tmp_path):
    add_proposal(db, "P")
    db.commit()
    calls = []
    report = refresh(steps=fake_steps(calls), backup_dir=tmp_path / "b")
    assert calls == ["sync", "identity", "index", "check"]
    assert report["ok"] and report["problems"] == [] and report["warnings"] == []
    assert list(report["steps"]) == ["backup", "sync", "identity", "index", "check"]
    assert report["steps"]["identity"] == {"linked": 3}                  # the stats, not the long step list
    assert report["rows_before"]["proposals"] == report["rows_after"]["proposals"] == 1
    assert len(list((tmp_path / "b").glob("dao_intelligence_*.db"))) == 1
    json.dumps(report)                                                   # it is written to a file


def test_a_failing_step_is_a_problem_and_the_later_steps_still_run(db, tmp_path):
    calls = []
    report = refresh(steps=fake_steps(calls, sync_all=boom), backup_dir=tmp_path / "b")
    assert calls == ["identity", "index", "check"]
    assert not report["ok"] and report["problems"] == ["sync failed: RuntimeError: network down"]


def test_without_a_backup_nothing_is_touched(db, tmp_path, monkeypatch):
    monkeypatch.setattr(refresh_module, "backup_database", boom)
    calls = []
    report = refresh(steps=fake_steps(calls), backup_dir=tmp_path / "b")
    assert calls == [] and not report["ok"] and "backup failed" in report["problems"][0]


def test_offline_and_no_backup_skip_their_steps(db, tmp_path):
    calls = []
    report = refresh(backup=False, online=False, steps=fake_steps(calls), backup_dir=tmp_path / "b")
    assert calls == ["identity", "index", "check"] and report["ok"]
    assert "backup" not in report["steps"] and not (tmp_path / "b").exists()


def test_incomplete_data_is_a_warning_not_a_failure(db, tmp_path):
    report = refresh(steps=fake_steps([], sync_status=status(forum_ok=False)), backup_dir=tmp_path / "b")
    assert report["ok"] and len(report["warnings"]) == 1
    assert "1 forum thread(s) not fully fetched" in report["warnings"][0]


def test_invalid_chunks_fail_the_run_and_foreign_or_old_ones_only_warn(db, tmp_path):
    bad = fake_steps([], check_index=lambda: {"invalid": 4, "legacy": 0})
    assert refresh(steps=bad, backup_dir=tmp_path / "b")["problems"] == ["4 chunk(s) in the index have invalid metadata"]
    odd = fake_steps([], sync_index=lambda conn: {"foreign": 1, "foreign_ids": ["x"]},
                     check_index=lambda: {"invalid": 0, "legacy": 2})
    report = refresh(steps=odd, backup_dir=tmp_path / "b")
    assert report["ok"] and len(report["warnings"]) == 2


def test_a_table_that_loses_rows_fails_the_run(db, tmp_path):
    for i in range(10):
        add_proposal(db, f"P{i}")
    db.commit()

    def losing_sync(conn, votes_proposals_limit):
        conn.execute("DELETE FROM proposals WHERE id IN ('P0', 'P1')")
        conn.commit()
        return {"current_status": status()}
    report = refresh(steps=fake_steps([], sync_all=losing_sync), backup_dir=tmp_path / "b")
    assert report["problems"] == ["proposals shrank from 10 to 8 rows"]


def test_table_counts_lists_the_watched_tables(db):
    add_proposal(db, "P")
    assert table_counts(db) == {"proposals": 1, "votes": 0, "forum_posts": 0, "resolved_identities": 0}


# ── the command line ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("problems, code", [([], 0), (["index failed"], 1)])
def test_main_writes_the_report_and_returns_the_exit_code(tmp_path, monkeypatch, problems, code):
    seen = {}

    def fake_refresh(backup, online):
        seen.update(backup=backup, online=online)
        return {"ok": not problems, "problems": problems, "warnings": []}
    monkeypatch.setattr(refresh_module, "refresh", fake_refresh)
    assert main(["--offline"], log_dir=tmp_path) == code
    assert seen == {"backup": True, "online": False}
    saved = json.loads((tmp_path / "last_refresh.json").read_text(encoding="utf-8"))
    assert saved["ok"] is (not problems) and saved["log_file"].endswith(".log")
    assert not (tmp_path / "refresh.lock").exists()                      # the lock is released
