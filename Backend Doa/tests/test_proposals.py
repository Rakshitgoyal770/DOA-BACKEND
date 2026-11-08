# tests/test_proposals.py
"""Proposal sync: unfinished proposals refresh by id, every new proposal is added,
only real changes count, and older databases gain the new columns."""

import json
import re
import sqlite3

import pytest

import clients.snapshot as snapshot
import db.schema as schema
import features.proposals.fetch as proposal_fetch

SPACE = "dao.eth"


def make(pid, created, state="closed", scores_state="final", votes=10, title=None, discussion=None):
    """A proposal shaped like Snapshot's API returns it."""
    return {"id": pid, "space": {"id": SPACE}, "title": title or f"Proposal {pid}", "body": "body",
            "choices": ["For", "Against"], "state": state, "votes": votes, "scores": [votes, 0],
            "scores_total": float(votes), "scores_state": scores_state, "created": created,
            "start": created, "end": created + 100, "link": None, "discussion": discussion,
            "author": "0xauthor"}


class FakeSnapshot:
    """Answers the three proposal queries we send: by id, created after X, and latest N."""

    def __init__(self, proposals):
        self.proposals = {p["id"]: p for p in proposals}
        self.requested_ids = []

    def __call__(self, query):
        if "space(id:" in query:
            space = re.search(r'space\(id: "([^"]+)"', query).group(1)
            return {"space": {"id": space, "name": "Test DAO", "about": "", "network": "1",
                              "proposalsCount": len(self.proposals), "followersCount": 7, "votesCount": 9}}
        first = int(re.search(r"first: (\d+)", query).group(1))
        if "id_in" in query:
            ids = re.findall(r'"([^"]+)"', re.search(r"id_in: \[(.*?)\]", query).group(1))
            self.requested_ids += ids
            return {"proposals": [self.proposals[i] for i in ids if i in self.proposals]}
        space = re.search(r'space: "([^"]+)"', query).group(1)
        mine = [p for p in self.proposals.values() if p["space"]["id"] == space]
        if "created_gte" in query:
            since = int(re.search(r"created_gte: (\d+)", query).group(1))
            page = sorted((p for p in mine if p["created"] >= since), key=lambda p: p["created"])
        else:
            page = sorted(mine, key=lambda p: p["created"], reverse=True)
        return {"proposals": page[:first]}


@pytest.fixture
def snap(monkeypatch):
    def install(proposals):
        fake = FakeSnapshot(proposals)
        monkeypatch.setattr(snapshot, "_run_query_retry", fake)
        monkeypatch.setattr(snapshot.time, "sleep", lambda s: None)
        monkeypatch.setattr(proposal_fetch, "CURATED_DAOS", [{"id": SPACE, "name": "Test DAO"}])
        return fake
    return install


def store(conn, p):
    """Save a proposal the way an earlier sync would have."""
    proposal_fetch._save_proposal(conn, p, "earlier")
    conn.commit()


def row(conn, pid):
    return conn.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()


# ── refreshing proposals we already have ─────────────────────────────────────

def test_active_proposal_outside_the_latest_window_still_gets_its_final_result(db, snap):
    store(db, make("old_active", created=1_000, state="active", scores_state="pending", votes=5))
    newer = [make(f"new{i}", created=2_000 + i) for i in range(50)]     # pushes it far down the list
    for p in newer:
        store(db, p)
    snap(newer + [make("old_active", created=1_000, state="closed", scores_state="final", votes=80)])

    proposal_fetch.sync_proposals(db)

    r = row(db, "old_active")
    assert (r["state"], r["scores_state"], r["votes_count"]) == ("closed", "final", 80)
    assert json.loads(r["scores_json"]) == [80, 0]


def test_closed_proposal_with_pending_scores_is_rechecked_until_final(db, snap):
    """Snapshot recalculates scores after a vote closes ('pending' -> 'final')."""
    store(db, make("p", created=1_000, state="closed", scores_state="pending", votes=7))
    snap([make("p", created=1_000, state="closed", scores_state="final", votes=9)])

    proposal_fetch.refresh_unfinished_proposals(db)

    assert (row(db, "p")["scores_state"], row(db, "p")["scores_total"]) == ("final", 9.0)


def test_finished_proposals_are_not_requested_again(db, snap):
    store(db, make("done", created=1_000))
    store(db, make("live", created=1_001, state="active", scores_state="pending"))
    fake = snap([make("done", created=1_000), make("live", created=1_001, state="active", scores_state="pending")])

    proposal_fetch.refresh_unfinished_proposals(db)

    assert fake.requested_ids == ["live"]


def test_any_edited_field_is_updated_and_counted_once(db, snap):
    store(db, make("p", created=1_000, state="active", scores_state="pending"))
    snap([make("p", created=1_000, state="active", scores_state="pending",
               title="Renamed", discussion="https://forum/t/x/1")])

    first = proposal_fetch.refresh_unfinished_proposals(db)
    second = proposal_fetch.refresh_unfinished_proposals(db)

    assert (row(db, "p")["title"], row(db, "p")["discussion_url"]) == ("Renamed", "https://forum/t/x/1")
    assert (first["changed"], second["changed"]) == (1, 0)


def test_rows_from_older_syncs_get_created_ts_filled(db, snap):
    store(db, make("legacy", created=1_000))
    db.execute("UPDATE proposals SET created_ts = NULL, scores_state = NULL")
    snap([make("legacy", created=1_000)])

    proposal_fetch.refresh_unfinished_proposals(db)

    assert (row(db, "legacy")["created_ts"], row(db, "legacy")["scores_state"]) == (1_000, "final")


def test_proposal_deleted_on_snapshot_is_reported(db, snap):
    store(db, make("gone", created=1_000, state="active", scores_state="pending"))
    snap([])
    assert proposal_fetch.refresh_unfinished_proposals(db)["not_on_snapshot"] == ["gone"]


# ── adding new proposals ─────────────────────────────────────────────────────

def test_every_new_proposal_is_added_even_more_than_one_page(db, snap):
    store(db, make("newest_we_have", created=1_000))
    # 1,500 new proposals, three per second, so page edges fall inside a second
    new = [make(f"n{i}", created=1_001 + i // 3) for i in range(1_500)]
    snap([make("newest_we_have", created=1_000)] + new)

    result = proposal_fetch.fetch_new_proposals(db)

    assert result["added"] == 1_500
    assert db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1_501


def test_a_dao_never_synced_starts_with_its_latest_proposals(db, snap):
    snap([make(f"p{i}", created=1_000 + i) for i in range(30)])

    proposal_fetch.fetch_new_proposals(db, initial_per_dao=5)

    ids = {r[0] for r in db.execute("SELECT id FROM proposals")}
    assert ids == {"p25", "p26", "p27", "p28", "p29"}


def test_nothing_new_means_nothing_written(db, snap):
    store(db, make("p", created=1_000))
    snap([make("p", created=1_000)])
    assert proposal_fetch.sync_proposals(db)["new"]["added"] == 0


def test_sync_stores_the_dao_row_that_the_dao_endpoints_read(db, snap):
    snap([make("p", created=1_000)])

    result = proposal_fetch.sync_proposals(db)

    space = db.execute("SELECT * FROM spaces WHERE id = ?", (SPACE,)).fetchone()
    assert (space["name"], space["proposals_count"], space["followers_count"]) == ("Test DAO", 1, 7)
    assert result["spaces"] == {"refreshed": 1, "failed": []}


# ── older databases ──────────────────────────────────────────────────────────

def test_old_proposals_table_gains_the_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE proposals (id TEXT PRIMARY KEY, space_id TEXT, title TEXT, state TEXT)")
    old.execute("INSERT INTO proposals VALUES ('p', 'dao.eth', 'Kept', 'closed')")
    old.commit(); old.close()
    monkeypatch.setattr(schema, "DB_PATH", path)

    conn = schema.get_connection()
    schema.get_connection().close()          # running again must not fail or duplicate columns

    columns = {r[1] for r in conn.execute("PRAGMA table_info(proposals)")}
    assert {"scores_state", "created_ts"} <= columns
    assert conn.execute("SELECT title FROM proposals WHERE id = 'p'").fetchone()[0] == "Kept"
    conn.close()
