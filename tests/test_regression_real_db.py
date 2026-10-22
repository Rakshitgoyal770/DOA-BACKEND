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


def test_golden_dataset_points_at_documents_that_exist():
    """An id-format change once made 5 of 7 expected sources unfindable, which
    would have scored the evaluation as if retrieval had failed."""
    from eval.golden_dataset import GOLDEN_DATASET
    from vector.embedding import get_collection
    ids = [i for case in GOLDEN_DATASET for i in case["ground_truth_context_ids"]]
    assert sorted(get_collection().get(ids=ids)["ids"]) == sorted(ids)


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


def test_chat_merges_sql_facts_into_the_response(client, monkeypatch):
    chunk = {"id": "forum_post_x", "document": "I support this.", "distance": 0.4,
             "metadata": {"source_type": "forum_post", "proposal_id": DEFILLAMA, "author": "someone"}}
    monkeypatch.setattr(chat_service, "retrieve", lambda *a, **k: [dict(chunk)])
    monkeypatch.setattr(chat_service, "answer_question", lambda q, chunks, facts=None: ("stub", "stub"))

    body = client.post("/chat", json={"query": "Why did it pass?", "proposal_id": DEFILLAMA}).json()

    assert body["proposal_facts"][0]["winning_choice"] == "For"
    assert body["sources"][0]["source_type"] == "forum_post"
