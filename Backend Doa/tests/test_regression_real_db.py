# tests/test_regression_real_db.py
"""
Regression checks against the real database.

These pin values we verified by hand on complete data, so a code change that
quietly alters a result fails here. They only read (opening a connection may
create missing indexes) and are skipped when db/dao_intelligence.db is absent.
"""

import pytest
from fastapi.testclient import TestClient

import db.schema as schema
from features.chat import service as chat_service
from features.chat import tools
from features.chat.context import proposal_facts
from features.forum.completeness import forum_completeness
from features.sync.audit import audit_collection_status
from features.votes.completeness import vote_completeness

pytestmark = [
    pytest.mark.real_db,
    pytest.mark.skipif(not schema.DB_PATH.exists(), reason="real database not present"),
]

DEFILLAMA = "0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2"   # Optimism, closed


@pytest.fixture(scope="module")
def conn():
    c = schema.get_connection()
    yield c
    c.close()


@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def test_known_proposal_facts_are_unchanged(conn):
    f = proposal_facts(conn, DEFILLAMA)
    assert f["title"] == "Season 2: Cycle 8: DefiLlama"
    assert f["winning_choice"] == "For"
    assert [r["share_pct"] for r in f["results"]] == [91.7, 1.4, 6.9]
    assert f["total_voters"] == 14194
    assert f["top_4_voters_share_pct"] == 50.4
    assert f["votes_partial"] is False


def test_known_proposal_votes_are_complete(conn):
    row = next(r for r in vote_completeness(conn) if r["proposal_id"] == DEFILLAMA)
    assert (row["stored"], row["expected"], row["status"]) == (14194, 14194, "complete")


def test_known_proposal_forum_thread_is_fully_stored(conn):
    """Was cut at Discourse's first page of 20 posts; the thread has 33."""
    t = next(t for t in forum_completeness(conn) if DEFILLAMA in t["proposal_ids"])
    assert (t["stored"], t["listed"], t["status"]) == (33, 33, "complete")


def test_forum_completeness_adds_up(conn):
    c = audit_collection_status(conn)["forum"]["completeness"]
    assert c["complete"] + c["partial"] + c["not_fetched"] + c["error"] == c["threads"]


def test_every_proposal_has_publish_time_and_score_status(conn):
    """Filled by the proposal sync; the 'new proposals' cursor depends on created_ts."""
    missing = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE created_ts IS NULL OR scores_state IS NULL").fetchone()[0]
    assert missing == 0


def test_audit_completeness_adds_up(conn):
    audit = audit_collection_status(conn)
    c = audit["votes"]["completeness"]
    assert c["complete"] + c["partial"] + c["missing"] + c["no_votes_on_snapshot"] == audit["total_proposals"]


@pytest.mark.parametrize("path", [
    "/", "/daos", "/daos/ens.eth", "/proposals?limit=3", f"/proposals/{DEFILLAMA}",
    f"/proposals/{DEFILLAMA}/concentration", "/sync/status", "/identities/stats",
    "/identities?limit=3", f"/identities/proposal/{DEFILLAMA}", "/identities/resolve/status",
])
def test_read_endpoints_respond(client, path):
    assert client.get(path).status_code == 200


def test_health_lists_every_registered_endpoint(client):
    """The old hand-written list had fallen behind (it missed 5 identity endpoints)."""
    endpoints = set(client.get("/").json()["endpoints"])
    assert {"POST /chat", "GET  /daos", "GET  /proposals/{proposal_id}/concentration",
            "POST /sync/run", "GET  /identities/proposal/{proposal_id}",
            "GET  /identities/wallet/{wallet_address}", "GET  /identities/{username}"} <= endpoints


@pytest.mark.parametrize("path", ["/daos/not-a-dao.eth", "/proposals/0xdead", "/identities/nobody_zzz"])
def test_unknown_items_return_404(client, path):
    assert client.get(path).status_code == 404


def test_concentration_endpoint_matches_chat_facts(client, conn):
    """Two code paths compute the top-4 share; with complete votes they must agree."""
    api = client.get(f"/proposals/{DEFILLAMA}/concentration?top_n=4").json()["top_n_share_pct"]
    assert api == proposal_facts(conn, DEFILLAMA)["top_4_voters_share_pct"]


def test_chat_response_carries_the_sources_and_the_lookups(client, conn, monkeypatch):
    chunk = {"id": "forum_post_x", "document": "I support this.", "distance": 0.4, "sql": {},
             "metadata": {"source_type": "forum_post", "proposal_id": DEFILLAMA, "author": "someone"}}
    evidence = [{"tool": "proposal_details", "arguments": {"proposal_id": DEFILLAMA},
                 "result": tools.proposal_details(conn, DEFILLAMA)},
                {"tool": "search_forum", "arguments": {"query": "why"}, "result": {"chunks": [chunk]}}]
    monkeypatch.setattr(chat_service, "gather_evidence", lambda *a: evidence)
    monkeypatch.setattr(chat_service, "answer_question", lambda *args, **kwargs: ("stub", "stub"))

    body = client.post("/chat", json={"query": "Why did it pass?", "proposal_id": DEFILLAMA}).json()

    assert body["lookups"][0]["result"]["winning_choice"] == "For"
    assert body["lookups"][1]["result"] == {"passages_found": 1}          # the passage itself is in "sources"
    assert body["sources"][0]["source_type"] == "forum_post"


# ── the chat lookups on real data: answers the old pipeline got wrong ─────────

def test_most_voters_across_all_daos_is_found(conn):
    """The old pipeline said 1,019 (it only saw the 3 proposals search returned)."""
    top = tools.list_proposals(conn, "voters", limit=1)
    assert top["proposals"][0]["voters"] == 63845 and top["proposals"][0]["dao"] == "Optimism Collective"
    held = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]          # grows with every data refresh
    assert top["scope"].startswith(f"all {held} proposals we hold for all 5 DAOs")


def test_the_largest_voter_on_oat_elections_and_their_ballot(conn):
    """The old pipeline named a smaller voter (maxlomu.eth)."""
    oat = tools.find_proposals(conn, "OAT Elections")[0]
    voter = tools.top_voters(conn, oat["proposal_id"], 1)["top_voters"][0]
    assert (voter["forum_username"], voter["voting_power"]) == ("entropy", 33030451.22)
    assert voter["ballot"] == "Pedro Breuer: 6600000, Patrick McCorry: 13200000, A.J. Warner: 13200000"


def test_griffs_vote_is_found_by_name(conn):
    """The old pipeline said there was no information about griff."""
    frozen = tools.find_proposals(conn, "Approve Release of Frozen ETH")[0]
    assert tools.person(conn, "griff", frozen["proposal_id"])["vote_on_this_proposal"] ==         {"ballot": "For", "voting_power": 9677958.25}


def test_ens_has_the_highest_average_silence_ratio(conn):
    ratios = {d["dao"]: d["avg_silence_ratio_pct"] for d in tools.dao_stats(conn)["daos"]}
    # The exact value moves with every data refresh (11.549 on 22 Oct 2026, 11.198 on 13 Nov 2026).
    assert max(ratios, key=ratios.get) == "ENS" and 5 < ratios["ENS"] < 25
