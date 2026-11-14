# tests/test_planner.py
"""features/chat/planner.py: understanding a question once, then a FIXED set of lookups and searches.

The model is a fake that returns a scripted JSON reply, and retrieval is a recorder: no LLM calls, no index."""

import json

import pytest

import features.chat.planner as planner
import features.chat.tools as tools
from features.chat.planner import (KINDS, PlanError, QuestionPlan, execute_plan, gather_planned, parse_plan,
                                   resolve_proposals, rule_plan, understand)
from tests.helpers import add_post, add_proposal

ARB = "arbitrumfoundation.eth"
OPT = "opcollective.eth"
WALLET = "0xAbC" + "0" * 37


def add_vote(db, pid, voter, vp, choice_json="1"):
    db.execute("INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at) "
               "VALUES (?, ?, ?, ?, ?, 0, 't')", (f"{pid}_{voter}", pid, voter, choice_json, vp))
    db.commit()


def plan_reply(**fields):
    return json.dumps({"kind": "arguments", **fields})


def fake_generate(reply, seen=None):
    def generate(messages):
        if seen is not None:
            seen.append(messages)
        return reply, "fake"
    return generate


def never(*args, **kwargs):
    raise AssertionError("the model must not be asked")


# ── rules: no model call ──────────────────────────────────────────────────────

@pytest.mark.parametrize("question", ["hi", "Hello!", "thanks", "Thank you.", "good morning"])
def test_a_plain_greeting_needs_no_model(question):
    assert rule_plan(question).kind == "greeting" and rule_plan(question).source == "rules"


@pytest.mark.parametrize("question, order", [
    ("Which proposal across all the DAOs had the most voters?", "voters"),
    ("What was the most voted proposal?", "voters"),
    ("What are the latest proposals?", "newest"),
    ("What's new?", "newest"),
    ("Are there any open votes right now?", "newest"),
    ("Which vote was the closest?", "closest"),
    ("Show me the most contested proposals", "closest"),
])
def test_a_plain_ranking_is_recognised_by_rule(question, order):
    plan = rule_plan(question)
    assert (plan.kind, plan.order_by, plan.source) == ("ranking", order, "rules")


def test_a_ranking_rule_reads_the_dao_and_the_number_asked_for():
    plan = rule_plan("What are the top 3 most voted proposals on Arbitrum?")
    assert (plan.order_by, plan.dao, plan.limit) == ("voters", ARB, 3)
    assert rule_plan("latest proposals").dao is None and rule_plan("top 50 most voted proposals").limit is None


@pytest.mark.parametrize("question", [
    "Who voted the most on the Frozen ETH proposal?",            # a person-shaped question
    "Why was the most voted proposal so popular?",
    "What did griff say about the latest proposal?",
    'What was decided about "Frozen ETH"?',
    "What is a DAO?",
])
def test_anything_that_is_not_plainly_a_ranking_goes_to_the_model(question):
    assert rule_plan(question) is None


def test_a_question_about_a_selected_proposal_is_never_a_ranking():
    assert rule_plan("Which one had the most voters?", proposal_id="P") is None
    assert rule_plan("hi", proposal_id="P").kind == "greeting"


# ── the model's reply ─────────────────────────────────────────────────────────

def test_a_valid_reply_becomes_a_validated_plan():
    plan = parse_plan('Sure!\n```json\n{"kind": "arguments", "dao": "Arbitrum DAO", "proposal": " Frozen ETH ", '
                      '"person": null, "search": "Why did people support Frozen ETH?", "order_by": "", "limit": null, '
                      '"comment": "extra keys are ignored"}\n```')
    assert (plan.kind, plan.dao, plan.proposal, plan.person, plan.order_by, plan.limit) == \
        ("arguments", ARB, "Frozen ETH", None, None, None)
    assert plan.source == "model"


def test_words_the_model_uses_for_nothing_become_none_and_an_unknown_dao_is_dropped():
    plan = parse_plan(plan_reply(dao="some other dao", proposal="null", person="None", search="N/A"))
    assert (plan.dao, plan.proposal, plan.person, plan.search) == (None, None, None, None)


@pytest.mark.parametrize("reply", [
    "I think this is about voting.",                                  # no JSON at all
    "{not json}",
    json.dumps({"kind": "poetry"}),                                   # a kind we do not have
    json.dumps({"dao": "ens"}),                                       # no kind
    json.dumps({"kind": "ranking", "limit": 99}),                     # out of range
    json.dumps({"kind": "ranking", "order_by": "alphabet"}),
    "",
])
def test_a_reply_that_is_not_a_valid_plan_is_an_error_the_caller_can_handle(reply):
    with pytest.raises(PlanError):
        parse_plan(reply)


def test_every_kind_is_explained_to_the_model_and_handled_by_the_plan():
    for kind in KINDS:
        assert f'"{kind}"' in planner.UNDERSTAND_PROMPT
        QuestionPlan(kind=kind)


def test_understand_uses_one_model_call_and_none_for_a_rule():
    seen = []
    plan = understand("Why did people support the Frozen ETH proposal?", generate=fake_generate(plan_reply(proposal="Frozen ETH"), seen))
    assert plan.proposal == "Frozen ETH" and len(seen) == 1
    assert seen[0][0]["role"] == "system" and seen[0][1] == {"role": "user", "content": "Why did people support the Frozen ETH proposal?"}
    assert understand("hi", generate=never).kind == "greeting"


def test_the_model_is_told_when_the_user_already_selected_a_proposal():
    seen = []
    understand("Why did people support it?", proposal_id="P", generate=fake_generate(plan_reply(), seen))
    assert "already selected the proposal" in seen[0][0]["content"]
    seen.clear()
    understand("Why did people support it?", generate=fake_generate(plan_reply(), seen))
    assert "already selected" not in seen[0][0]["content"]


# ── words in the question -> a proposal ───────────────────────────────────────

def found(*items):
    return [{"proposal_id": pid, "title_words_matched": matched} for pid, matched in items]


def test_the_best_matching_proposals_are_used_and_at_most_two():
    assert resolve_proposals(found(("A", "3 of 3"), ("B", "2 of 3")), "frozen eth funds") == ["A"]
    assert resolve_proposals(found(("A", "3 of 3"), ("B", "3 of 3"), ("C", "3 of 3")), "frozen eth funds") == ["A", "B"]


def test_a_weak_match_is_not_used_because_the_writer_would_get_the_wrong_proposal():
    assert resolve_proposals(found(("A", "1 of 3")), "frozen eth funds") == []
    assert resolve_proposals(found(("A", "1 of 2")), "frozen eth") == ["A"]               # half of the words is enough
    assert resolve_proposals({"error": "No proposal title contains those words."}, "x y") == []
    assert resolve_proposals([], "x y") == [] and resolve_proposals(found(("A", "1 of 1")), "") == []


# ── the lookups, per kind ─────────────────────────────────────────────────────

@pytest.fixture
def searches(monkeypatch):
    """Records every search_forum call that reaches retrieval and returns one passage."""
    calls = []

    def retrieve(query, n_results, where, max_distance):
        calls.append({"query": query, "n": n_results, "where": where})
        return [{"id": f"forum_post_P_{len(calls)}", "document": f"passage {len(calls)}", "distance": 0.3,
                 "metadata": {"source_type": "forum_post", "proposal_id": "P", "author": "carol"}}]
    monkeypatch.setattr(tools, "retrieve", retrieve)
    return calls


@pytest.fixture
def world(db):
    add_proposal(db, "P", space_id=ARB, title="Frozen ETH release", votes_count=2, scores=[9, 1])
    add_proposal(db, "Q", space_id=OPT, title="Grants cycle", votes_count=1, scores=[5, 0])
    add_post(db, 1, "P", "carol", "I support the release.")
    add_vote(db, "P", WALLET, 9.0, "1")
    return db


def run(world, plan, query="the question", **kw):
    return execute_plan(world, plan, query, **kw)


def tools_run(evidence):
    return [e["tool"] for e in evidence]


def test_a_greeting_and_a_general_question_look_nothing_up(world, searches):
    assert run(world, QuestionPlan(kind="greeting")) == [] and run(world, QuestionPlan(kind="general")) == []
    assert searches == []


def test_a_ranking_is_one_lookup_and_no_passages(world, searches):
    evidence = run(world, QuestionPlan(kind="ranking", order_by="voters", dao=ARB, limit=1))
    assert tools_run(evidence) == ["list_proposals"] and searches == []
    assert evidence[0]["arguments"] == {"order_by": "voters", "dao": ARB, "limit": 1}
    assert evidence[0]["result"]["proposals"][0]["title"] == "Frozen ETH release" and evidence[0]["planned"]


def test_dao_numbers_are_one_lookup_and_no_passages(world, searches):
    assert tools_run(run(world, QuestionPlan(kind="dao_stats", dao=ARB))) == ["dao_stats"] and searches == []


def test_a_result_question_finds_the_proposal_and_gets_its_numbers_without_passages(world, searches):
    evidence = run(world, QuestionPlan(kind="proposal_result", proposal="Frozen ETH"))
    assert tools_run(evidence) == ["find_proposals", "proposal_details"] and searches == []
    assert evidence[1]["arguments"] == {"proposal_id": "P"} and evidence[1]["result"]["total_voters"] == 2


def test_who_voted_gets_the_details_the_biggest_voters_and_the_named_person(world, searches):
    evidence = run(world, QuestionPlan(kind="who_voted", proposal="Frozen ETH", person="carol"))
    assert tools_run(evidence) == ["find_proposals", "proposal_details", "top_voters", "person"]
    assert evidence[3]["arguments"] == {"name": "carol", "proposal_id": "P"} and searches == []


def test_arguments_always_search_the_discussion_and_the_proposals_text_scoped_to_the_proposal(world, searches):
    evidence = run(world, QuestionPlan(kind="arguments", proposal="Frozen ETH", search="Why did people support Frozen ETH?"), n_results=6)
    assert tools_run(evidence) == ["find_proposals", "proposal_details", "search_forum", "search_forum"]
    assert [(c["query"], c["n"], c["where"]) for c in searches] == [
        ("Why did people support Frozen ETH?", 6, {"$and": [{"proposal_id": "P"}, {"source_type": "forum_post"}]}),
        ("Why did people support Frozen ETH?", 2, {"$and": [{"proposal_id": "P"}, {"source_type": "proposal_body"}]})]


def test_the_proposal_the_user_selected_is_used_without_looking_for_it(world, searches):
    evidence = run(world, QuestionPlan(kind="arguments", proposal="something else"), query="Why support it?", proposal_id="P")
    assert tools_run(evidence) == ["proposal_details", "search_forum", "search_forum"]
    assert all({"proposal_id": "P"} in c["where"]["$and"] for c in searches)
    assert searches[0]["query"] == "Why support it?"                       # no search sentence: the question itself


def test_with_no_proposal_the_passages_are_searched_in_the_dao_or_everywhere(world, searches):
    run(world, QuestionPlan(kind="arguments", dao=ARB))
    assert searches[0]["where"] == {"$and": [{"space_id": ARB}, {"source_type": "forum_post"}]}
    searches.clear()
    run(world, QuestionPlan(kind="arguments"))
    assert searches[0]["where"] == {"source_type": "forum_post"}


def test_a_proposal_that_cannot_be_found_still_gets_a_search_and_the_writer_sees_the_failed_lookup(world, searches):
    evidence = run(world, QuestionPlan(kind="arguments", proposal="lunar base colony"))
    assert tools_run(evidence) == ["find_proposals", "search_forum", "search_forum"]
    assert "error" in evidence[0]["result"] and searches[0]["where"] == {"source_type": "forum_post"}


def test_advice_searches_for_and_against_and_the_text(world, searches):
    evidence = run(world, QuestionPlan(kind="advice", proposal="Frozen ETH", search="Should I vote for Frozen ETH?"))
    assert tools_run(evidence) == ["find_proposals", "proposal_details", "search_forum", "search_forum", "search_forum"]
    assert [c["query"] for c in searches] == ["Arguments in favour of: Should I vote for Frozen ETH?",
                                              "Concerns and arguments against: Should I vote for Frozen ETH?",
                                              "Should I vote for Frozen ETH?"]
    assert searches[2]["where"]["$and"][1] == {"source_type": "proposal_body"}


def test_what_a_proposal_asks_for_searches_its_own_text(world, searches):
    evidence = run(world, QuestionPlan(kind="proposal_content", proposal="Frozen ETH"))
    assert tools_run(evidence) == ["find_proposals", "proposal_details", "search_forum"]
    assert searches[0]["where"] == {"$and": [{"proposal_id": "P"}, {"source_type": "proposal_body"}]}


def test_a_person_gets_their_record_and_their_posts_through_the_author_filter(world, searches):
    evidence = run(world, QuestionPlan(kind="person", person="Carol", proposal="Frozen ETH"))
    assert tools_run(evidence) == ["find_proposals", "person", "search_forum"]
    assert {"author_lower": "carol"} in searches[0]["where"]["$and"] and {"proposal_id": "P"} in searches[0]["where"]["$and"]


def test_a_person_the_model_did_not_find_is_a_question_the_agent_must_handle(world, searches):
    assert run(world, QuestionPlan(kind="person")) == [] and searches == []


def test_other_is_left_to_the_agent(world):
    with pytest.raises(PlanError):
        run(world, QuestionPlan(kind="other"))


def test_each_lookup_is_reported_as_soon_as_it_ran(world, searches):
    seen = []
    evidence = run(world, QuestionPlan(kind="proposal_result", proposal="Frozen ETH"), on_lookup=seen.append)
    assert seen == evidence


def test_the_evidence_has_the_shape_the_writer_already_reads(world, searches):
    from features.chat.prompt import build_prompt
    evidence = run(world, QuestionPlan(kind="arguments", proposal="Frozen ETH"))
    user = build_prompt("Why did people support it?", evidence)[1]["content"]
    assert "DATABASE FACTS" in user and "find_proposals(" in user and "[Source 1 - forum_post by carol" in user


# ── the whole of stage 1 ──────────────────────────────────────────────────────

def test_gather_planned_understands_then_looks_up(world, searches):
    evidence, plan = gather_planned("Why did people support the Frozen ETH proposal?",
                                    generate=fake_generate(plan_reply(proposal="Frozen ETH")))
    assert plan.kind == "arguments" and tools_run(evidence)[-1] == "search_forum"


def test_gather_planned_raises_when_the_question_is_not_understood(world, searches):
    with pytest.raises(PlanError):
        gather_planned("something odd", generate=fake_generate("no idea"))
    with pytest.raises(PlanError):
        gather_planned("something odd", generate=fake_generate(plan_reply(kind="other")))


# ── run_chat: planned by default, the agent as the fallback ───────────────────

import features.chat.llm as llm
import features.chat.service as service


@pytest.fixture
def planned(monkeypatch, world, searches):
    """CHAT_PIPELINE=planned; the understanding step and the writer are fakes that record their messages."""
    monkeypatch.setenv("CHAT_PIPELINE", "planned")
    seen = {"understand": [], "writer": []}

    def understanding(messages):
        seen["understand"].append(messages)
        return plan_reply(proposal="Frozen ETH"), "fake"

    def writer(messages):
        seen["writer"].append(messages)
        return "The vote passed [Facts]. Carol supports it [Source 1].", "fake"
    monkeypatch.setattr(llm, "generate", understanding)
    monkeypatch.setattr(service, "generate", writer)
    return seen


def test_the_pipeline_is_planned_unless_the_agent_is_asked_for(monkeypatch):
    monkeypatch.delenv("CHAT_PIPELINE", raising=False)
    assert service.pipeline() == "planned"
    for value, expected in (("agent", "agent"), (" AGENT ", "agent"), ("planned", "planned"), ("nonsense", "planned")):
        monkeypatch.setenv("CHAT_PIPELINE", value)
        assert service.pipeline() == expected


def test_a_question_is_answered_from_a_plan_one_understanding_call_and_one_writer_call(planned):
    out = service.run_chat("Why did people support the Frozen ETH proposal?")
    assert len(planned["understand"]) == 1 and len(planned["writer"]) == 1
    assert out["plan"]["mode"] == "planned" and out["plan"]["kind"] == "arguments" and out["plan"]["proposal"] == "Frozen ETH"
    assert [e["tool"] for e in out["evidence"]] == ["find_proposals", "proposal_details", "search_forum", "search_forum"]
    assert out["answer"] == "The vote passed [Facts]. Carol supports it [Source 1]." and out["citations"]["ok"]
    assert "[Source 1 - forum_post by carol" in planned["writer"][0][1]["content"]


def test_a_ranking_question_costs_no_understanding_call(planned, monkeypatch):
    monkeypatch.setattr(llm, "generate", never)
    out = service.run_chat("Which proposal had the most voters?")
    assert out["plan"] == {"mode": "planned", "kind": "ranking", "order_by": "voters", "source": "rules"}
    assert [e["tool"] for e in out["evidence"]] == ["list_proposals"] and out["chunks"] == []


def test_a_question_the_planner_cannot_place_goes_to_the_agent(planned, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda messages: (plan_reply(kind="other"), "fake"))
    monkeypatch.setattr(service, "gather_evidence", lambda *a: [{"tool": "dao_stats", "arguments": {}, "result": {}}])
    out = service.run_chat("Compare the quorum of Aave and ENS and also tell me a joke")
    assert out["plan"]["mode"] == "agent" and out["plan"]["fallback_reason"].startswith("PlanError")
    assert [e["tool"] for e in out["evidence"]] == ["dao_stats"]


def test_a_reply_that_is_not_a_plan_goes_to_the_agent(planned, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda messages: ("Sorry, I cannot do that.", "fake"))
    monkeypatch.setattr(service, "gather_evidence", lambda *a: [])
    assert service.run_chat("Why did they vote that way?")["plan"]["mode"] == "agent"


def test_a_bug_in_the_planner_never_leaves_a_question_unanswered(planned, monkeypatch):
    monkeypatch.setattr(service, "gather_planned", lambda *a: (_ for _ in ()).throw(KeyError("boom")))
    monkeypatch.setattr(service, "gather_evidence", lambda *a: [])
    out = service.run_chat("Why did people support it?")
    assert out["plan"]["mode"] == "agent" and "KeyError" in out["plan"]["fallback_reason"]


def test_when_every_provider_is_down_the_agent_is_not_tried_as_well(planned, monkeypatch):
    def down(messages):
        raise RuntimeError("All providers failed. Last error: quota")
    monkeypatch.setattr(llm, "generate", down)
    monkeypatch.setattr(service, "gather_evidence", never)
    with pytest.raises(RuntimeError, match="All providers failed"):
        service.run_chat("Why did people support the Frozen ETH proposal?")


def test_the_agent_pipeline_never_calls_the_planner(planned, monkeypatch):
    monkeypatch.setenv("CHAT_PIPELINE", "agent")
    monkeypatch.setattr(service, "gather_planned", never)
    monkeypatch.setattr(service, "gather_evidence", lambda *a: [])
    assert service.run_chat("Why did people support it?")["plan"] == {"mode": "agent"}


def test_the_selected_proposal_and_the_number_of_passages_reach_the_lookups(planned, searches):
    service.run_chat("Why did people support it?", proposal_id="P", n_results=7)
    assert searches[0]["n"] == 7 and {"proposal_id": "P"} in searches[0]["where"]["$and"]
    assert "already selected the proposal" in planned["understand"][0][0]["content"]


def test_when_two_proposals_match_equally_both_get_their_details_and_the_passages_cover_the_dao(db, searches):
    add_proposal(db, "T", space_id=ARB, title="Release of Frozen ETH", votes_count=1, scores=[1, 0])
    add_proposal(db, "C", space_id=ARB, title="[Constitutional] AIP: Release of Frozen ETH", votes_count=2, scores=[2, 0])
    evidence = execute_plan(db, QuestionPlan(kind="arguments", proposal="Release Frozen ETH", dao=ARB), "q")
    assert [(e["tool"], e["arguments"].get("proposal_id")) for e in evidence[:3]] == [
        ("find_proposals", None), ("proposal_details", "T"), ("proposal_details", "C")] or         sorted(e["arguments"]["proposal_id"] for e in evidence if e["tool"] == "proposal_details") == ["C", "T"]
    assert searches[0]["where"] == {"$and": [{"space_id": ARB}, {"source_type": "forum_post"}]}
