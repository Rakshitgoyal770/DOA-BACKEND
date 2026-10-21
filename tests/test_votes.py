# tests/test_votes.py
"""Vote completeness, the full vote fetch, and sync_all using it (Phase 1, items 1 and 2)."""

import features.votes.fetch as vote_fetch
from features.sync import runner
from features.sync.audit import audit_collection_status
from features.votes.completeness import vote_completeness, vote_status
from tests.helpers import add_proposal, add_votes, count


class FakeSnapshot:
    """Stands in for clients.snapshot.iter_all_votes: holds every proposal's votes
    and records which proposals were asked for, and from which timestamp."""

    def __init__(self, votes_per_proposal: dict[str, int], fail_for: set = frozenset()):
        self.votes = {
            pid: [{"voter": f"0xVoter{i}", "created": 1_700_000_000 + i, "choice": 1, "vp": 1.0}
                  for i in range(n)]
            for pid, n in votes_per_proposal.items()
        }
        self.fail_for = fail_for
        self.calls = []   # (proposal_id, start_ts)

    def __call__(self, proposal_id, start_ts=0, **_):
        self.calls.append((proposal_id, start_ts))
        if proposal_id in self.fail_for:
            raise ConnectionError("network down")
        return iter([v for v in self.votes[proposal_id] if v["created"] >= start_ts])


def statuses(conn):
    return {r["proposal_id"]: r["status"] for r in vote_completeness(conn)}


# ── vote_status: the single completeness rule ────────────────────────────────

def test_vote_status_covers_every_case():
    assert vote_status(0, 0) == "no_votes"
    assert vote_status(None, 0) == "no_votes"
    assert vote_status(5, 0) == "missing"
    assert vote_status(5, 2) == "partial"
    assert vote_status(5, 5) == "complete"
    assert vote_status(5, 6) == "complete"   # votes arrived after the proposal count was saved


def test_vote_completeness_reports_stored_expected_and_resume_point(db):
    add_proposal(db, "A", votes_count=3); add_votes(db, "A", 3)
    add_proposal(db, "B", votes_count=5); add_votes(db, "B", 2)
    rows = {r["proposal_id"]: r for r in vote_completeness(db)}
    assert rows["A"]["status"] == "complete"
    assert (rows["B"]["stored"], rows["B"]["expected"], rows["B"]["status"]) == (2, 5, "partial")
    assert rows["B"]["last_vote_ts"] == 1_700_000_001   # newest stored vote


# ── fetch_all_votes ───────────────────────────────────────────────────────────

def test_fetch_all_votes_completes_only_incomplete_proposals(db, monkeypatch):
    add_proposal(db, "complete", votes_count=3); add_votes(db, "complete", 3)
    add_proposal(db, "partial", votes_count=5);  add_votes(db, "partial", 2)
    add_proposal(db, "big", votes_count=1500)    # more than the old 500-vote cap
    add_proposal(db, "empty", votes_count=0)
    fake = FakeSnapshot({"complete": 3, "partial": 5, "big": 1500, "empty": 0})
    monkeypatch.setattr(vote_fetch, "iter_all_votes", fake)

    result = vote_fetch.fetch_all_votes(db, max_proposals=10)

    asked = dict(fake.calls)
    assert set(asked) == {"partial", "big"}               # complete/empty are not re-fetched
    assert asked["partial"] == 1_700_000_001              # resumes from the newest stored vote
    assert asked["big"] == 0                              # nothing stored yet: start at the beginning
    assert count(db, "votes", "proposal_id = 'big'") == 1500
    assert statuses(db) == {"complete": "complete", "partial": "complete",
                            "big": "complete", "empty": "no_votes"}
    assert result["proposals_processed"] == 2 and result["failed"] == []


def test_fetch_all_votes_twice_creates_no_duplicates(db, monkeypatch):
    add_proposal(db, "P", votes_count=1200)
    fake = FakeSnapshot({"P": 1200})
    monkeypatch.setattr(vote_fetch, "iter_all_votes", fake)

    vote_fetch.fetch_all_votes(db)
    vote_fetch.fetch_all_votes(db)

    assert count(db, "votes") == 1200
    assert len(fake.calls) == 1        # second run sees the proposal is complete


def test_fetch_all_votes_keeps_going_when_one_proposal_fails(db, monkeypatch):
    add_proposal(db, "bad", votes_count=2)
    add_proposal(db, "good", votes_count=3)
    monkeypatch.setattr(vote_fetch, "iter_all_votes", FakeSnapshot({"bad": 2, "good": 3}, fail_for={"bad"}))

    result = vote_fetch.fetch_all_votes(db)

    assert result["failed"] == ["bad"]
    assert statuses(db) == {"bad": "missing", "good": "complete"}


def test_fetch_all_votes_does_smallest_proposals_first(db, monkeypatch):
    for pid, n in (("large", 50), ("small", 5), ("medium", 20)):
        add_proposal(db, pid, votes_count=n)
    fake = FakeSnapshot({"large": 50, "small": 5, "medium": 20})
    monkeypatch.setattr(vote_fetch, "iter_all_votes", fake)

    vote_fetch.fetch_all_votes(db, max_proposals=2)

    assert [pid for pid, _ in fake.calls] == ["small", "medium"]


# ── sync_all now uses the complete fetch (item 1) ────────────────────────────

def test_sync_all_fetches_every_vote_not_just_500(db, monkeypatch):
    add_proposal(db, "P", votes_count=1500)
    monkeypatch.setattr(runner, "fetch_new_proposals", lambda conn, first_per_dao: {"inserted": 0})
    monkeypatch.setattr(runner, "fetch_forum_threads", lambda conn, limit: {})
    monkeypatch.setattr(vote_fetch, "iter_all_votes", FakeSnapshot({"P": 1500}))

    result = runner.sync_all(db)

    assert count(db, "votes") == 1500
    assert result["current_status"]["votes"]["completeness"]["is_complete"] is True


# ── the audit reports completeness (item 2) ──────────────────────────────────

def test_audit_reports_completeness_and_names_the_worst_gaps(db):
    add_proposal(db, "done", votes_count=2);      add_votes(db, "done", 2)
    add_proposal(db, "small_gap", votes_count=5); add_votes(db, "small_gap", 4)
    add_proposal(db, "big_gap", votes_count=90);  add_votes(db, "big_gap", 10)
    add_proposal(db, "none", votes_count=7)
    add_proposal(db, "zero", votes_count=0)

    c = audit_collection_status(db)["votes"]["completeness"]

    assert (c["complete"], c["partial"], c["missing"], c["no_votes_on_snapshot"]) == (1, 2, 1, 1)
    assert c["is_complete"] is False
    assert [r["proposal_id"] for r in c["incomplete_proposals"]] == ["big_gap", "none", "small_gap"]
    # a proposal with 0 votes on Snapshot is not "missing" votes
    assert audit_collection_status(db)["votes"]["proposals_missing_votes"] == 1
