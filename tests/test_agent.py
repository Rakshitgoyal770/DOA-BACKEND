# tests/test_agent.py
"""
features/chat/agent.py gather_evidence: stage 1, the loop where the model asks for lookups.

The model is replaced by a script of replies, so these tests cost no LLM calls. They pin the
mechanics: a lookup request is run by OUR code, its result goes back to the model, the loop
stops, and what comes out is the evidence the writer will use.
"""

import copy
import itertools
import json
from types import SimpleNamespace as NS

import features.chat.agent as agent
from features.chat.tools import TOOLS
from tests.helpers import add_proposal


def ask(tool, **arguments):
    """One lookup request in the shape the provider SDKs return."""
    return NS(id=f"call_{tool}_{len(arguments)}", function=NS(name=tool, arguments=json.dumps(arguments)))


def reply(*calls, text=None):
    """A model reply: lookup requests (tool_calls) or, with none, plain text."""
    return NS(content=text, tool_calls=list(calls) or None)


class ScriptedModel:
    """Stands in for generate_with_tools: returns the scripted replies and records what it was sent."""

    def __init__(self, replies):
        self.replies, self.sent = iter(replies), []

    def __call__(self, messages, tools):
        self.sent.append({"messages": copy.deepcopy(messages), "tools": tools})
        return next(self.replies), "fake"


def use(monkeypatch, replies):
    model = ScriptedModel(replies)
    monkeypatch.setattr(agent, "generate_with_tools", model)
    return model


def test_the_requested_lookup_is_run_and_its_result_goes_back_to_the_model(db, monkeypatch):
    add_proposal(db, "A", title="Small", votes_count=5)
    add_proposal(db, "B", title="Huge", votes_count=500)
    model = use(monkeypatch, [reply(ask("list_proposals", order_by="voters", limit=1)), reply(text="DONE")])

    evidence = agent.gather_evidence("which proposal had the most voters?")

    assert [(e["tool"], e["arguments"]) for e in evidence] == [("list_proposals", {"order_by": "voters", "limit": 1})]
    assert evidence[0]["result"]["proposals"][0]["title"] == "Huge"      # raw result, computed by OUR code
    assert len(model.sent) == 2                                          # request, then "DONE"
    assert model.sent[0]["tools"] is TOOLS                               # the model is told what it may ask for
    roles = [m["role"] for m in model.sent[1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]              # the second call carries the result
    assert '"title": "Huge"' in model.sent[1]["messages"][3]["content"]


def test_a_question_that_needs_no_lookup_returns_no_evidence(db, monkeypatch):
    model = use(monkeypatch, [reply(text="DONE")])
    assert agent.gather_evidence("What is a DAO?") == []
    assert len(model.sent) == 1


def test_the_selected_proposal_is_told_to_the_model_and_filled_into_its_lookups(db, monkeypatch):
    add_proposal(db, "P", title="Approve Release of Frozen ETH", votes_count=1)
    model = use(monkeypatch, [reply(ask("person", name="griff")), reply(text="DONE")])    # model forgot the id

    evidence = agent.gather_evidence("How did griff vote?", proposal_id="P")

    user = model.sent[0]["messages"][1]["content"]
    assert "Approve Release of Frozen ETH" in user and "proposal_id P" in user
    assert evidence[0]["arguments"] == {"name": "griff", "proposal_id": "P"}            # what ran is what is recorded


def test_the_same_lookup_twice_adds_nothing(db, monkeypatch):
    add_proposal(db, "A", votes_count=5)
    same = ask("list_proposals", order_by="voters")
    model = use(monkeypatch, [reply(same, same), reply(text="DONE")])

    evidence = agent.gather_evidence("q")

    assert len(evidence) == 1
    assert model.sent[1]["messages"][-1]["content"] == "Already looked up above with these arguments."


def test_a_model_that_never_stops_asking_is_cut_off(db, monkeypatch):
    add_proposal(db, "A", votes_count=5)
    endless = (reply(ask("find_proposals", words=f"w{i}")) for i in itertools.count())
    model = use(monkeypatch, endless)

    evidence = agent.gather_evidence("q")

    assert len(model.sent) == agent.MAX_ROUNDS == len(evidence)         # then the writer works with what exists


def test_unreadable_arguments_and_failing_lookups_do_not_crash_the_loop(db, monkeypatch):
    broken = NS(id="c1", function=NS(name="person", arguments='{"name": '))        # cut-off JSON
    use(monkeypatch, [reply(broken), reply(text="DONE")])

    evidence = agent.gather_evidence("q")

    assert evidence[0]["arguments"] == {} and "TypeError" in evidence[0]["result"]["error"]   # the model can read it


def test_each_lookup_is_reported_as_soon_as_it_ran(db, monkeypatch):
    use(monkeypatch, [reply(ask("dao_stats")), reply(text="DONE")])
    seen = []
    agent.gather_evidence("q", on_lookup=seen.append)
    assert [e["tool"] for e in seen] == ["dao_stats"]


def test_the_agent_is_told_to_gather_not_to_answer():
    assert "do not answer" in agent.FETCHER_PROMPT.lower() and "DONE" in agent.FETCHER_PROMPT


def test_a_third_forum_search_is_refused(db, monkeypatch):
    """A live run searched five times with n=8, 20, 50, 100 (capped at 8): 88 s and the same passages."""
    monkeypatch.setattr(agent, "run_tool", lambda conn, name, arguments, defaults: {"chunks": []})
    searches = (reply(ask("search_forum", query=f"question number {i}")) for i in range(5))
    model = use(monkeypatch, itertools.chain(searches, [reply(text="DONE")]))

    evidence = agent.gather_evidence("q")

    assert len(evidence) == agent.MAX_SEARCHES == 2
    refused = model.sent[agent.MAX_SEARCHES + 1]["messages"][-1]["content"]          # the model is told why
    assert "Search limit reached" in refused


def test_counts_must_come_from_the_database_not_from_passages():
    """'How many different people discussed X?' was answered 4 by counting names in 8 passages; it is 9."""
    assert "Never count from" in agent.FETCHER_PROMPT and "proposal_details" in agent.FETCHER_PROMPT
    from features.chat.prompt import SYSTEM_PROMPT
    assert "Never count people or posts yourself from the sources" in SYSTEM_PROMPT


def test_total_lookups_are_capped(db, monkeypatch):
    """gpt-oss-20b once called proposal_details for every proposal (43 s each) instead of one ranking."""
    ran = []
    monkeypatch.setattr(agent, "run_tool", lambda conn, name, arguments, defaults: ran.append(arguments) or {"ok": 1})
    wide = reply(*[ask("proposal_details", proposal_id=f"0x{i}") for i in range(10)])
    model = use(monkeypatch, [wide, reply(text="DONE")])

    evidence = agent.gather_evidence("q")

    assert len(evidence) == len(ran) == agent.MAX_LOOKUPS
    assert "Lookup limit reached" in model.sent[1]["messages"][-1]["content"]


def test_the_agent_is_told_to_use_one_ranking_and_the_proposal_text_for_what_it_asks():
    assert "ONE call answers it" in agent.FETCHER_PROMPT and "one by one" in agent.FETCHER_PROMPT
    assert 'source_type "proposal_body"' in agent.FETCHER_PROMPT


def test_news_means_the_newest_proposals_and_greetings_need_no_lookup():
    """'HI WHATS THE NEWS TODAY??' made no lookup, and the bot said it had no source material."""
    assert "News" in agent.FETCHER_PROMPT and "order_by newest" in agent.FETCHER_PROMPT
    assert 'greetings ("hi")' in agent.FETCHER_PROMPT


def test_the_agent_is_told_to_search_with_sentences():
    assert "full descriptive sentence" in agent.FETCHER_PROMPT and "match poorly" in agent.FETCHER_PROMPT


def test_the_agent_is_told_not_to_repeat_searches():
    """A live run made five near-identical forum searches (79 s, and most of the free token limit)."""
    assert "Run each lookup ONCE" in agent.FETCHER_PROMPT


def test_a_skipped_forum_search_is_run_for_a_question_that_asks_for_reasons(db, monkeypatch):
    """The model is the only one choosing lookups; when it skips the search the writer has no passage."""
    ran, seen = [], []
    def fake_run_tool(conn, name, arguments, defaults):
        for k, v in defaults.items():
            if v is not None:
                arguments.setdefault(k, v)                       # like the real run_tool
        ran.append((name, dict(arguments)))
        return {"chunks": [{"id": "c1"}]}
    monkeypatch.setattr(agent, "run_tool", fake_run_tool)
    use(monkeypatch, [reply(ask("proposal_details", proposal_id="P")), reply(text="DONE")])   # numbers only

    evidence = agent.gather_evidence("Why did delegates support it?", proposal_id="P", on_lookup=seen.append)

    assert [e["tool"] for e in evidence] == ["proposal_details", "search_forum"]
    net = evidence[1]
    assert net["automatic"] is True and "automatic" not in evidence[0]
    assert net["arguments"] == {"query": "Why did delegates support it?", "n": agent.SAFETY_NET_PASSAGES,
                                "proposal_id": "P"}              # the question as written, in the selected proposal
    assert ran[-1][0] == "search_forum" and seen[-1] is net      # the terminal chat is told as well


def test_no_extra_search_when_the_model_searched_or_the_question_is_not_about_reasons(db, monkeypatch):
    ran = []
    monkeypatch.setattr(agent, "run_tool", lambda conn, name, arguments, defaults: ran.append(name) or {"chunks": []})
    use(monkeypatch, [reply(ask("search_forum", query="what people argued")), reply(text="DONE")])
    assert len(agent.gather_evidence("Why did delegates support it?")) == 1          # the model did search
    for question in ("hi", "What is a DAO?", "Which proposal had the most voters?", "How many voters were there?"):
        use(monkeypatch, [reply(text="DONE")])
        assert agent.gather_evidence(question) == [], question
    assert ran == ["search_forum"]                                                   # only the model's own search ran


def test_an_automatic_search_that_finds_nothing_is_still_evidence(db, monkeypatch):
    """The writer then sees that the search found nothing, and says so instead of guessing."""
    monkeypatch.setattr(agent, "run_tool", lambda conn, name, arguments, defaults: {"chunks": [], "note": "nothing close enough to the query"})
    use(monkeypatch, [reply(text="DONE")])
    evidence = agent.gather_evidence("What concerns were raised about the lunar base?")
    assert len(evidence) == 1 and evidence[0]["automatic"] and evidence[0]["result"]["chunks"] == []


def test_which_questions_ask_for_passages():
    """Text-seeking wording triggers it; counts never do (the 'said 4, true 9' mistake); 'For / Against' is a ballot."""
    yes = ["Why did delegates support it?", "What arguments were made against releasing the frozen ETH?",
           "What did griff say on the forum about the Frozen ETH release?", "How do delegates feel about the AIP?",
           "What does the DefiLlama grant proposal ask for?", "What concerns were raised?", "Should I vote for this?",
           "Why vote For and why vote Against the grant?", "What was discussed about the quorum change?"]
    no = ["hi", "thanks!", "What is a DAO?", "Which DAO has the most proposals?", "List the top 3 proposals by turnout",
          "How many voters did the Frozen ETH proposal have?", "How many different people discussed this proposal?",
          "What share of ENS proposals had forum discussion?", "How many people argued against it?",
          "Among ENS proposals with two or three options (such as For / Against), which had the closest result?",
          "What was the result of the proposal?", "HI WHATS THE NEWS TODAY??"]
    assert [q for q in yes if not agent.wants_passages(q)] == []
    assert [q for q in no if agent.wants_passages(q)] == []


# ── Where control goes next ───────────────────────────────────────────────────
# What the evidence becomes (the writer's prompt) is tested in tests/test_prompt.py; the two
# stages together in tests/test_chat_service.py.
