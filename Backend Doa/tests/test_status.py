# tests/test_status.py
"""Is a proposal open for voting right now? features/metrics.py proposal_status and where it is used.

The clock is always fixed (a `now` argument, or a patched metrics.utc_now), so these tests give the
same answer on any day."""

import pytest
from fastapi.testclient import TestClient

import features.chat.tools as tools
import features.metrics as metrics
from features.chat.context import proposal_facts
from features.chat.prompt import SYSTEM_PROMPT
from features.metrics import STATUS_MEANS, proposal_status
from tests.helpers import add_proposal

START, END = 1_000, 2_000          # a voting window, in epoch seconds
ARB = "arbitrumfoundation.eth"


def row(state, start=START, end=END, scores_state=None, fetched_at=None):
    return {"state": state, "start_ts": start, "end_ts": end, "scores_state": scores_state, "fetched_at": fetched_at}


def status(now, **kw):
    return proposal_status(row(**kw), now=now)["status"]


# ── the window, against the clock ─────────────────────────────────────────────

@pytest.mark.parametrize("now, label, expected", [
    (START - 1, "pending", "upcoming"),
    (START,     "pending", "open"),            # the first second of voting is open (label is behind the clock)
    (START,     "active",  "open"),
    (END - 1,   "active",  "open"),            # the last second is still open
    (START - 1, "active",  "open"),            # a label ahead of the clock is believed: it can only be behind
])
def test_inside_or_before_the_window(now, label, expected):
    assert status(now, state=label) == expected


def test_a_stale_active_label_cannot_keep_a_finished_vote_open():
    """The bug this file exists for: stored 'active', but the voting window is over."""
    result = proposal_status(row("active", scores_state="pending"), now=END)         # END itself is already over
    assert result["status"] == "ended_unsettled"
    assert result["stale_label"] is True and result["stored_state"] == "active"
    assert result["seconds_left"] is None


@pytest.mark.parametrize("label, scores_state, expected", [
    ("closed", "final",   "closed"),
    ("active", "final",   "closed"),            # Snapshot finished the count; the label is just old
    ("closed", "pending", "ended_unsettled"),   # voting ended, scores not final yet
    ("active", "pending", "ended_unsettled"),
    ("closed", None,      "closed"),            # older rows have no scores_state
    ("active", None,      "ended_unsettled"),
])
def test_after_the_window_closed_needs_final_scores(label, scores_state, expected):
    assert status(END + 500, state=label, scores_state=scores_state) == expected


def test_a_closed_label_is_believed_even_if_the_clock_says_open():
    """Snapshot can end a vote early; a label never runs ahead of reality."""
    result = proposal_status(row("closed", scores_state="final"), now=START + 10)
    assert result["status"] == "closed" and result["stale_label"] is False


def test_missing_dates_fall_back_to_the_label_and_nothing_known_is_unknown():
    assert status(5_000, state="active", start=None, end=None) == "open"
    assert status(5_000, state="pending", start=None, end=None) == "upcoming"
    assert status(5_000, state="closed", start=None, end=None, scores_state="final") == "closed"
    assert proposal_status(row(None, start=None, end=None), now=5_000)["status"] == "unknown"
    assert set(STATUS_MEANS) == {"upcoming", "open", "ended_unsettled", "closed", "unknown"}


# ── the extra fields ──────────────────────────────────────────────────────────

def test_seconds_left_only_while_open_and_the_age_of_our_data():
    open_ = proposal_status(row("active", fetched_at="1970-01-01T00:10:00+00:00"), now=1_500)
    assert (open_["seconds_left"], open_["voting_ends"], open_["data_age_seconds"]) == (500, END, 900)
    assert proposal_status(row("closed", scores_state="final"), now=5_000)["seconds_left"] is None
    assert proposal_status(row("active", fetched_at="garbage"), now=1_500)["data_age_seconds"] is None
    assert proposal_status(row("active", fetched_at="1970-01-01T00:10:00Z"), now=1_500)["data_age_seconds"] == 900
    assert proposal_status(row("active", fetched_at="2999-01-01T00:00:00Z"), now=1_500)["data_age_seconds"] == 0


def test_it_reads_sqlite_rows_and_rows_with_missing_columns(db):
    add_proposal(db, "P", state="active", start_ts=START, end_ts=END)
    full = db.execute("SELECT * FROM proposals WHERE id = 'P'").fetchone()
    assert proposal_status(full, now=1_500)["status"] == "open"
    narrow = db.execute("SELECT state FROM proposals WHERE id = 'P'").fetchone()        # no dates, no scores_state
    assert proposal_status(narrow, now=1_500)["status"] == "open"                       # falls back to the label


def test_the_default_clock_is_utc_now(monkeypatch):
    monkeypatch.setattr(metrics, "utc_now", lambda: END + 1)
    assert proposal_status(row("active"))["status"] == "ended_unsettled"


# ── the chat lookups ──────────────────────────────────────────────────────────

@pytest.fixture
def frozen(monkeypatch):
    """Clock after every test proposal's window (default window ends 1_700_100_000), so a stored 'active' is stale."""
    monkeypatch.setattr(metrics, "utc_now", lambda: 1_800_000_000)


def test_a_stale_active_vote_is_reported_as_ended_and_never_as_the_winner(db, frozen):
    add_proposal(db, "A", space_id=ARB, title="Stale", votes_count=50, state="active", scores=[80, 20])
    add_proposal(db, "B", space_id=ARB, title="Done", votes_count=900, scores=[60, 40])
    out = tools.list_proposals(db, "voters", dao="arbitrum")
    by_title = {p["title"]: p for p in out["proposals"]}
    assert by_title["Stale"]["status"] == "ended_unsettled" and by_title["Stale"]["result"] == "provisional: For 80.0%"
    assert by_title["Done"]["status"] == "closed" and by_title["Done"]["result"] == "winner: For 60.0%"
    assert all("state" not in p for p in out["proposals"])                  # the writer sees one word, not two
    assert out["status_means"]["ended_unsettled"] == STATUS_MEANS["ended_unsettled"]


def test_list_proposals_says_how_old_the_data_is(db, frozen):
    add_proposal(db, "A", space_id=ARB)
    add_proposal(db, "B", space_id=ARB)
    db.execute("UPDATE proposals SET fetched_at = '2026-10-21T07:00:00+00:00' WHERE id = 'A'")
    db.execute("UPDATE proposals SET fetched_at = '2026-10-22T09:36:29+00:00' WHERE id = 'B'")
    assert tools.list_proposals(db, "voters")["data_as_of"] == "2026-10-22"


def test_a_vote_that_has_not_opened_yet_is_upcoming_when_the_clock_is_before_its_window(db, monkeypatch):
    """The real clock is later than this window, so this only passes if the lookups really use the frozen clock."""
    monkeypatch.setattr(metrics, "utc_now", lambda: 1_600_000_000)          # before the default start, 1_700_000_000
    add_proposal(db, "A", space_id=ARB, title="Soon", state="pending", scores=[0, 0])
    out = tools.list_proposals(db, "newest", dao="arbitrum")
    assert out["proposals"][0]["status"] == "upcoming"
    assert tools.find_proposals(db, "soon")[0]["status"] == "upcoming"
    assert proposal_facts(db, "A")["status"] == "upcoming"


def test_the_closest_vote_leaves_out_votes_that_have_not_settled(db, frozen):
    add_proposal(db, "T", space_id=ARB, title="Tight", state="closed", scores=[52, 48])
    add_proposal(db, "S", space_id=ARB, title="StaleActive", state="active", scores=[51, 49])
    db.execute("UPDATE proposals SET scores_state = 'pending' WHERE id = 'S'")
    out = tools.list_proposals(db, "closest", dao="arbitrum")
    assert [p["title"] for p in out["proposals"]] == ["Tight"]


def test_find_proposals_shows_the_status(db, frozen):
    add_proposal(db, "A", space_id=ARB, title="Treasury grant", state="active")
    found = tools.find_proposals(db, "treasury")
    assert found[0]["status"] == "ended_unsettled" and "state" not in found[0]


def test_proposal_details_has_no_winner_until_the_result_is_final(db, frozen):
    add_proposal(db, "A", space_id=ARB, title="Stale", votes_count=5, state="active", scores=[80, 20])
    add_proposal(db, "B", space_id=ARB, title="Done", votes_count=5, scores=[60, 40])
    db.execute("UPDATE proposals SET fetched_at = '2026-10-22T09:36:29+00:00' WHERE id = 'A'")
    stale, done = proposal_facts(db, "A"), proposal_facts(db, "B")
    assert (stale["status"], stale["winning_choice"], stale["leading_choice"]) == ("ended_unsettled", None, "For")
    assert (done["status"], done["winning_choice"], done["leading_choice"]) == ("closed", "For", None)
    assert stale["status_means"] == STATUS_MEANS["ended_unsettled"] and stale["data_as_of"] == "2026-10-22"
    assert "state" not in stale and stale["voting_ends"] == "2023-11-16"        # 1_700_100_000 -> 16 Nov 2023


def test_an_open_vote_is_open_in_the_details(db, monkeypatch):
    monkeypatch.setattr(metrics, "utc_now", lambda: 1_700_050_000)
    add_proposal(db, "A", space_id=ARB, state="active", scores=[80, 20])
    facts = proposal_facts(db, "A")
    assert (facts["status"], facts["winning_choice"], facts["leading_choice"]) == ("open", None, "For")


def test_the_writer_is_told_how_to_use_status():
    assert "status" in SYSTEM_PROMPT and "ended_unsettled" in SYSTEM_PROMPT
    assert "never the winner" in SYSTEM_PROMPT


# ── the REST API ──────────────────────────────────────────────────────────────

def test_the_api_reports_status_next_to_the_stored_state(db, frozen):
    from main import app
    add_proposal(db, "A", space_id=ARB, title="Stale", votes_count=5, state="active", scores=[80, 20])
    add_proposal(db, "B", space_id=ARB, title="Done", votes_count=9, scores=[60, 40])
    with TestClient(app) as client:
        listing = {p["title"]: p for p in client.get("/proposals").json()}
        detail = client.get("/proposals/A").json()
    assert (listing["Stale"]["state"], listing["Stale"]["status"]) == ("active", "ended_unsettled")
    assert (listing["Done"]["state"], listing["Done"]["status"]) == ("closed", "closed")
    assert detail["status"] == "ended_unsettled"
