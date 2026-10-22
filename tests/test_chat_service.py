# tests/test_chat_service.py
"""features/chat/service.py run_chat: the one pipeline used by POST /chat and the eval."""

import features.chat.service as service
from tests.helpers import add_identity, add_post, add_proposal, add_votes

WALLET = "0xAbC" + "0" * 37


def chunk(pid, author="carol"):
    return {"id": f"forum_post_{pid}_1", "document": "I support this.", "distance": 0.3,
            "metadata": {"source_type": "forum_post", "proposal_id": pid, "author": author}}


def test_no_close_chunk_means_no_llm_call(db, monkeypatch):
    monkeypatch.setattr(service, "retrieve", lambda *a, **k: [])
    monkeypatch.setattr(service, "answer_question", lambda *a: (_ for _ in ()).throw(AssertionError("LLM called")))

    assert service.run_chat("why?", "P") == {"chunks": [], "facts": [], "answer": None, "provider": None}


def test_prompt_gets_sql_facts_and_the_authors_vote(db, monkeypatch):
    add_proposal(db, "P", votes_count=1, choices=["For", "Against"], scores=[9, 0])
    add_votes(db, "P", 1, voter_prefix=WALLET[:-1], vp=9.0)        # voter == WALLET
    add_post(db, 1, "P", "carol", "I support this.")
    add_identity(db, "carol", WALLET.lower(), "high")
    seen = {}

    def fake_llm(messages):
        seen["prompt"] = messages[1]["content"]      # the user message the LLM would receive
        return "ok", "fake"

    monkeypatch.setattr(service, "retrieve", lambda *a, **k: [chunk("P")])
    monkeypatch.setattr(service, "generate", fake_llm)

    out = service.run_chat("why?", "P")

    assert (out["answer"], out["provider"]) == ("ok", "fake")
    assert out["facts"][0]["winning_choice"] == "For"
    assert "by carol (voting power 9.0, voted For, wallet link: high)" in seen["prompt"]
    assert "PROPOSAL FACTS" in seen["prompt"]


def test_search_is_scoped_to_the_requested_proposal(db, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "retrieve", lambda q, n_results, where: calls.append((n_results, where)) or [])
    service.run_chat("why?", "P", n_results=7)
    service.run_chat("why?")
    assert calls == [(7, {"proposal_id": "P"}), (5, None)]
