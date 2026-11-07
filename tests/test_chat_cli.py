# tests/test_chat_cli.py
"""features/chat/cli.py: the terminal chat finds proposals, scopes questions, and survives bad input."""

import builtins

import features.chat.cli as cli
from tests.helpers import add_proposal


def test_find_matches_every_word_of_the_title(db):
    add_proposal(db, "A", title="Season 2: Cycle 8: DefiLlama")
    add_proposal(db, "B", title="Season 2: Cycle 8: Velodrome")
    assert [p["id"] for p in cli.find_proposals("cycle defillama")] == ["A"]
    assert {p["id"] for p in cli.find_proposals("season")} == {"A", "B"}
    assert cli.find_proposals("nothing like this") == []


def test_a_session_scopes_the_question_to_the_chosen_proposal(db, monkeypatch, capsys):
    add_proposal(db, "0xabc", title="Season 2: Cycle 8: DefiLlama")
    typed = iter(["/find defillama", "/use 1", "How did the vote go?", "/use 99", "/all", "Another?", "/quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(typed))
    asked = []
    monkeypatch.setattr(cli, "run_chat", lambda q, proposal_id=None, on_lookup=None: asked.append((q, proposal_id)) or
                        {"answer": "It passed.", "provider": "fake", "chunks": [], "evidence": []})

    cli.main()

    assert asked == [("How did the vote go?", "0xabc"), ("Another?", None)]     # /use scoped it, /all cleared it
    out = capsys.readouterr().out
    assert "Now talking about: Season 2: Cycle 8: DefiLlama" in out
    assert "Use a number from /find" in out                                    # /use 99 is rejected, no crash


def test_lookups_are_shown_as_they_happen_and_listed_afterwards(db, monkeypatch, capsys):
    evidence = [{"tool": "list_proposals", "arguments": {"order_by": "voters", "limit": 1},
                 "result": {"proposals": [{"title": "Huge", "voters": 63845}]}}]

    def fake_run_chat(q, proposal_id=None, on_lookup=None):
        on_lookup(evidence[0])                                             # the agent reports each lookup live
        return {"answer": "Huge had the most voters.", "provider": "fake", "chunks": [], "evidence": evidence}

    typed = iter(["Which proposal had the most voters?", "/lookups", "/quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(typed))
    monkeypatch.setattr(cli, "run_chat", fake_run_chat)

    cli.main()

    out = capsys.readouterr().out
    assert "... looked up list_proposals(order_by=voters, limit=1)" in out     # shown while it works
    assert "1 lookups, 0 sources" in out
    assert '"voters": 63845' in out                                            # /lookups shows the result
