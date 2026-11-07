# tests/test_tools.py
"""
features/chat/tools.py: the lookups the agent may ask for.

Why they exist: "which proposal had the most voters across all DAOs?" cannot be answered by
vector search (it finds similar TEXT), and an LLM must not compute numbers itself. So the
model names a lookup and we run it. Each test below pins a behaviour that once gave a wrong
answer, or that keeps the model from producing one.
"""

import json

import pytest

import features.chat.tools as tools
from tests.helpers import add_identity, add_post, add_proposal

ARB = "arbitrumfoundation.eth"
OPT = "opcollective.eth"
WALLET = "0xAbC" + "0" * 37


def add_vote(db, pid, voter, vp, choice_json="1"):
    db.execute("INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at) "
               "VALUES (?, ?, ?, ?, ?, 0, 't')", (f"{pid}_{voter}", pid, voter, choice_json, vp))
    db.commit()


def set_created(db, pid, ts):
    db.execute("UPDATE proposals SET created_ts = ? WHERE id = ?", (ts, pid))
    db.commit()


# ── naming a DAO ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("arbitrum", ARB), ("Arbitrum DAO", ARB), ("arbitrumfoundation.eth", ARB),
    ("op collective", OPT), ("ENS", "ens.eth"),
    ("tokens and lenses", None),          # "ens" inside words is not ENS
    ("", None), (None, None), ("some other dao", None),
])
def test_resolve_dao(text, expected):
    assert tools.resolve_dao(text) == expected


# ── finding a proposal by its title ──────────────────────────────────────────

def test_find_proposals_ranks_by_how_many_title_words_match(db):
    add_proposal(db, "A", title="OAT Elections")
    add_proposal(db, "B", title="Special Voting Cycle: Grants Elections")
    add_proposal(db, "C", title="Unrelated")
    found = tools.find_proposals(db, 'OAT Elections')
    assert [p["proposal_id"] for p in found] == ["A", "B"]
    assert found[0]["title_words_matched"] == "2 of 2"                  # the model can tell the best match
    assert found[1]["title_words_matched"] == "1 of 2"


def test_find_proposals_can_be_limited_to_one_dao_and_reports_misses(db):
    add_proposal(db, "A", space_id=ARB, title="Treasury grant")
    add_proposal(db, "B", space_id=OPT, title="Treasury grant")
    assert [p["proposal_id"] for p in tools.find_proposals(db, "treasury", dao="optimism")] == ["B"]
    assert "error" in tools.find_proposals(db, "nothing like this")
    assert "Unknown DAO" in tools.find_proposals(db, "treasury", dao="nowhere")["error"]


# ── ranking proposals ────────────────────────────────────────────────────────

def test_the_most_voted_proposal_is_found_across_all_daos(db):
    """The question that used to answer '1,019' because search only saw 3 proposals."""
    add_proposal(db, "A", space_id=ARB, title="Small", votes_count=1019, scores=[9, 1])
    add_proposal(db, "B", space_id=OPT, title="Huge", votes_count=63845, scores=[9, 1])
    out = tools.list_proposals(db, "voters", limit=1)
    assert [p["title"] for p in out["proposals"]] == ["Huge"]
    assert out["proposals"][0]["voters"] == 63845
    assert "all 2 proposals we hold for all 5 DAOs" in out["scope"]       # the model sees what it ranked
    assert "not their full history" in out["scope"]


def test_ranking_can_be_limited_to_one_dao(db):
    add_proposal(db, "A", space_id=ARB, votes_count=5)
    add_proposal(db, "B", space_id=OPT, votes_count=500)
    out = tools.list_proposals(db, "voters", dao="arbitrum")
    assert [p["proposal_id"] for p in out["proposals"]] == ["A"]
    assert "Arbitrum DAO" in out["scope"]


def test_an_open_vote_is_leading_never_the_winner(db):
    add_proposal(db, "A", space_id=ARB, title="Open", votes_count=50, state="active", scores=[80, 20])
    add_proposal(db, "B", space_id=ARB, title="Done", votes_count=900, scores=[60, 40])
    results = {p["title"]: p["result"] for p in tools.list_proposals(db, "voters", dao="arbitrum")["proposals"]}
    assert results == {"Open": "leading: For 80.0%", "Done": "winner: For 60.0%"}


def test_newest_orders_by_publish_time(db):
    for pid, ts in (("old", 100), ("new", 300), ("mid", 200)):
        add_proposal(db, pid, space_id=ARB)
        set_created(db, pid, ts)
    assert [p["proposal_id"] for p in tools.list_proposals(db, "newest", dao="arbitrum")["proposals"]] \
        == ["new", "mid", "old"]


def test_closest_vote_ignores_elections_with_many_options(db):
    """In a nine-candidate election an 18% winner is normal, not a close vote."""
    add_proposal(db, "E", space_id=ARB, title="Election", state="closed",
                 choices=list("abcdefghi"), scores=[18, 17, 16, 15, 14, 10, 5, 3, 2])
    add_proposal(db, "T", space_id=ARB, title="Tight", state="closed", scores=[52, 48])
    add_proposal(db, "W", space_id=ARB, title="Wide", state="closed", scores=[95, 5])
    add_proposal(db, "O", space_id=ARB, title="Open", state="active", scores=[51, 49])    # not closed yet
    out = tools.list_proposals(db, "closest", dao="arbitrum")
    assert [p["title"] for p in out["proposals"]] == ["Tight", "Wide"]


def test_list_limit_is_bounded_and_unknown_daos_are_reported(db):
    for i in range(12):
        add_proposal(db, f"P{i}", votes_count=i)
    assert len(tools.list_proposals(db, "voters", limit=100)["proposals"]) == 10
    assert len(tools.list_proposals(db, "voters", limit=0)["proposals"]) == 1
    assert "Unknown DAO" in tools.list_proposals(db, "voters", dao="nowhere")["error"]


# ── per-DAO numbers and one proposal ─────────────────────────────────────────

def test_dao_stats_covers_all_five_daos_or_one(db):
    add_proposal(db, "A", space_id=ARB, votes_count=100, scores=[60, 40])
    add_post(db, 1, "A", "carol", "hi")
    everyone = tools.dao_stats(db)
    assert len(everyone["daos"]) == 5
    assert "forum posters / voters" in everyone["silence_ratio_means"]
    arb = tools.dao_stats(db, "arbitrum")["daos"]
    assert [d["dao"] for d in arb] == ["Arbitrum DAO"]
    assert arb[0]["proposals_ingested"] == 1 and arb[0]["avg_silence_ratio_pct"] == 1.0


def test_proposal_details_returns_the_shared_facts_or_a_readable_error(db):
    add_proposal(db, "A", votes_count=10, scores=[9, 1])
    assert tools.proposal_details(db, "A")["winning_choice"] == "For"
    assert "find_proposals" in tools.proposal_details(db, "nope")["error"]    # tells the model what to do


# ── voters and people ────────────────────────────────────────────────────────

def test_top_voters_lists_the_biggest_ballots_with_their_identities(db):
    """'Who is the largest voter on OAT Elections?' answered with a smaller voter."""
    add_proposal(db, "P", title="Election", choices=["Ann", "Bob", "Cy"], votes_count=3, scores=[1, 1, 1])
    add_vote(db, "P", WALLET, 33.0, '{"1": 10, "3": 23}')
    add_vote(db, "P", "0xSmall", 4.0, "2")
    add_vote(db, "P", "0xTiny", 1.0, "2")
    add_identity(db, "carol", WALLET.lower(), "high")
    out = tools.top_voters(db, "P", n=2)
    first, second = out["top_voters"]
    assert (first["voting_power"], first["forum_username"]) == (33.0, "carol")
    assert first["ballot"] == "Ann: 10, Cy: 23"                          # split of the voter's power
    assert first["share_of_voting_power_pct"] == 86.8                    # 33 of 38
    assert second["ballot"] == "Bob" and second["forum_username"] is None
    assert "split their voting power" in out["ballot_means"]             # keeps the model from misreading it
    assert "error" in tools.top_voters(db, "nope")


def test_person_by_forum_username_gives_the_vote_and_the_posts(db):
    add_proposal(db, "P", votes_count=1, scores=[9, 0])
    add_vote(db, "P", WALLET, 9.0, "1")
    add_post(db, 1, "P", "Carol", "I support this because the budget is small.")
    add_identity(db, "carol", WALLET.lower(), "high")
    out = tools.person(db, "@Carol", "P")
    assert out["wallet"] == WALLET.lower() and out["wallet_link_confidence"] == "high"
    assert out["vote_on_this_proposal"] == {"ballot": "For", "voting_power": 9.0}
    assert "budget is small" in out["posts_on_this_proposal"][0]["text"]


def test_person_without_a_vote_says_so_and_unknown_people_are_errors(db):
    add_proposal(db, "P", votes_count=0)
    add_post(db, 1, "P", "dave", "hello")
    assert tools.person(db, "dave", "P")["vote_on_this_proposal"] == "no vote from this wallet in our data"
    assert "No forum user" in tools.person(db, "nobody_zzz")["error"]


def test_person_without_a_proposal_summarises_activity(db):
    add_proposal(db, "P", title="Frozen ETH", votes_count=1)
    add_vote(db, "P", WALLET, 1.0)
    add_post(db, 1, "P", "carol", "hi")
    add_identity(db, "carol", WALLET.lower(), "high")
    out = tools.person(db, "carol")
    assert out["votes_in_our_data"] == 1 and out["proposals_posted_on"] == ["Frozen ETH"]


# ── searching the forum ──────────────────────────────────────────────────────

def fake_retrieve(calls, chunks):
    def retrieve(query, n_results, where, max_distance):
        calls.append({"n": n_results, "where": where, "max_distance": max_distance})
        return [dict(c) for c in chunks]
    return retrieve


def forum_chunk(author="carol", pid="P"):
    return {"id": f"forum_post_{pid}_1", "document": "I support this.", "distance": 0.3,
            "metadata": {"source_type": "forum_post", "proposal_id": pid, "author": author}}


def test_search_attaches_each_authors_wallet_and_vote(db, monkeypatch):
    """The 'said vs voted' data: a passage arrives with what its author voted."""
    add_proposal(db, "P", title="Frozen ETH", votes_count=1, scores=[9, 0])
    add_vote(db, "P", WALLET, 9.0, "1")
    add_post(db, 1, "P", "carol", "I support this.")
    add_identity(db, "carol", WALLET.lower(), "high")
    monkeypatch.setattr(tools, "retrieve", fake_retrieve([], [forum_chunk()]))
    chunk = tools.search_forum(db, "why support")["chunks"][0]
    assert chunk["sql"]["voted"] == "For" and chunk["sql"]["voting_power"] == 9.0
    assert chunk["proposal_title"] == "Frozen ETH"


def test_search_filters_by_proposal_and_author(db, monkeypatch):
    add_proposal(db, "P")
    add_post(db, 1, "P", "Griff", "hello")                    # the index keeps the original spelling
    calls = []
    monkeypatch.setattr(tools, "retrieve", fake_retrieve(calls, []))

    tools.search_forum(db, "anything", proposal_id="P")
    tools.search_forum(db, "anything", author="@GRIFF")
    tools.search_forum(db, "anything", proposal_id="P", author="griff", n=99)

    assert calls[0] == {"n": 5, "where": {"proposal_id": "P"}, "max_distance": tools.MAX_DISTANCE_ONE_PROPOSAL}
    assert calls[1] == {"n": 5, "where": {"author": "Griff"}, "max_distance": tools.MAX_DISTANCE_ONE_AUTHOR}
    assert calls[2]["where"] == {"$and": [{"proposal_id": "P"}, {"author": "Griff"}]}
    assert calls[2]["n"] == 8                                                          # bounded


def test_the_distance_cutoff_is_loosest_where_the_search_is_already_narrow(db, monkeypatch):
    """One keyword scores 0.72-0.95 against a proposal's posts: a global 0.7 cutoff said 'no discussion'."""
    assert tools.MAX_DISTANCE_ANYWHERE < tools.MAX_DISTANCE_ONE_PROPOSAL < tools.MAX_DISTANCE_ONE_AUTHOR
    calls = []
    monkeypatch.setattr(tools, "retrieve", fake_retrieve(calls, []))
    tools.search_forum(db, "treasury risks")                                          # nothing narrows it
    assert calls[0]["max_distance"] == tools.MAX_DISTANCE_ANYWHERE


def test_the_model_is_told_to_write_sentences_not_keywords():
    query = next(t for t in tools.TOOLS if t["function"]["name"] == "search_forum")["function"]["parameters"]["properties"]["query"]
    assert "full descriptive sentence" in query["description"] and "Never single keywords" in query["description"]


def test_search_can_fetch_the_proposals_own_text(db, monkeypatch):
    """'What does the proposal ask for?' got a forum post: the proposal body was never searched for."""
    add_proposal(db, "P")
    calls = []
    monkeypatch.setattr(tools, "retrieve", fake_retrieve(calls, []))
    tools.search_forum(db, "What does the proposal ask for?", proposal_id="P", source_type="proposal_body")
    assert calls[0]["where"] == {"$and": [{"proposal_id": "P"}, {"source_type": "proposal_body"}]}
    schema = next(t for t in tools.TOOLS if t["function"]["name"] == "search_forum")["function"]["parameters"]
    assert schema["properties"]["source_type"]["enum"] == ["proposal_body", "forum_post"]


def test_search_reports_unknown_authors_and_empty_results(db, monkeypatch):
    monkeypatch.setattr(tools, "retrieve", fake_retrieve([], []))
    assert "No forum posts by 'ghost'" in tools.search_forum(db, "x", author="ghost")["error"]
    assert tools.search_forum(db, "x") == {"chunks": [], "note": "nothing close enough to the query"}


# ── running a lookup ─────────────────────────────────────────────────────────

def test_a_selected_proposal_is_filled_in_when_the_model_leaves_it_out(db):
    """A user who selected a proposal is asking about THAT proposal, however the model phrases it."""
    add_proposal(db, "P", votes_count=1)
    arguments = {"name": "nobody_zzz"}
    tools.run_tool(db, "person", arguments, {"proposal_id": "P", "n": 5})
    assert arguments == {"name": "nobody_zzz", "proposal_id": "P"}       # no "n": person has no such parameter

    explicit = {"proposal_id": "Q"}
    tools.run_tool(db, "proposal_details", explicit, {"proposal_id": "P"})
    assert explicit == {"proposal_id": "Q"}                              # what the model named wins

    nulls = {"words": "elections", "dao": None}
    tools.run_tool(db, "find_proposals", nulls, {"proposal_id": "P"})
    assert nulls == {"words": "elections"}                               # null means "not given"; find_proposals takes no proposal


def test_a_bad_call_becomes_an_error_the_model_can_read(db):
    assert "KeyError" in tools.run_tool(db, "drop_all_tables", {})["error"]           # not in FUNCTIONS: cannot run
    assert "TypeError" in tools.run_tool(db, "dao_stats", {"colour": "red"})["error"]


def test_every_lookup_has_a_description_for_the_model():
    described = {t["function"]["name"] for t in tools.TOOLS}
    assert described == set(tools.FUNCTIONS) and len(described) == 7
    for t in tools.TOOLS:
        assert t["function"]["description"] and t["function"]["parameters"]["type"] == "object"


def test_the_agent_sees_short_passages_but_results_are_never_unbounded(db):
    chunk = forum_chunk()
    chunk.update(document="word " * 500, sql={"voted": "For", "link_confidence": "high"}, proposal_title="T")
    view = json.loads(tools.fetcher_view("search_forum", {"chunks": [chunk]}))["passages"][0]
    assert len(view["text"]) <= tools.VIEW_CHARS + len(" [...]") and view["voted"] == "For"
    assert tools.fetcher_view("dao_stats", {"a": 1}) == '{"a": 1}'                    # other results unchanged
    assert tools.result_json({"x": "y" * 10_000}).endswith("[...cut]")
    assert len(tools.result_json({"x": "y" * 10_000})) < tools.MAX_RESULT_CHARS + 20


# ── Where control goes next ───────────────────────────────────────────────────
# The loop that calls these lookups is tested in tests/test_agent.py; the full pipeline
# in tests/test_chat_service.py. If a lookup returns a number that looks wrong, compare it
# with the endpoint of the same name (/daos, /proposals): both use features/metrics.py.
