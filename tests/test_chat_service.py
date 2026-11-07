# tests/test_chat_service.py
"""features/chat/service.py run_chat (agent -> writer) and features/chat/llm.py (providers, retry)."""

from types import SimpleNamespace as NS

import features.chat.agent as agent
import features.chat.llm as llm
import features.chat.service as service
import features.chat.tools as tools
from tests.helpers import add_identity, add_post, add_proposal, add_votes

WALLET = "0xAbC" + "0" * 37


def chunk(pid, author="carol"):
    return {"id": f"forum_post_{pid}_1", "document": "I support this.", "distance": 0.3,
            "metadata": {"source_type": "forum_post", "proposal_id": pid, "author": author}}


def entry(tool, result, **arguments):
    return {"tool": tool, "arguments": arguments, "result": result}


# ── the two stages together ──────────────────────────────────────────────────

def test_a_ranking_question_is_answered_from_lookups_even_when_no_passage_is_close(db, monkeypatch):
    """'most voters across all DAOs' used to answer from 3 searched proposals; now the ranking is looked up."""
    add_proposal(db, "A", space_id="arbitrumfoundation.eth", title="Small", votes_count=1019, scores=[9, 1])
    add_proposal(db, "B", space_id="opcollective.eth", title="Huge", votes_count=63845, scores=[9, 1])
    seen = {}
    script = iter([NS(content=None, tool_calls=[NS(id="c1", function=NS(
                        name="list_proposals", arguments='{"order_by": "voters", "limit": 1}'))]),
                   NS(content="DONE", tool_calls=None)])
    monkeypatch.setattr(agent, "generate_with_tools", lambda messages, tool_list: (next(script), "fake"))
    monkeypatch.setattr(service, "generate", lambda messages: seen.update(prompt=messages[1]["content"]) or ("ok", "fake"))

    out = service.run_chat("Which proposal across all the DAOs had the most voters?")

    assert (out["answer"], out["provider"], out["chunks"]) == ("ok", "fake", [])
    assert "63845" in seen["prompt"] and "all 2 proposals we hold" in seen["prompt"]
    assert out["evidence"][0]["tool"] == "list_proposals"


def test_what_an_author_voted_reaches_the_writers_prompt(db, monkeypatch):
    """The 'said vs voted' path: forum search -> author's wallet -> their vote -> the source header."""
    add_proposal(db, "P", votes_count=1, choices=["For", "Against"], scores=[9, 0])
    add_votes(db, "P", 1, voter_prefix=WALLET[:-1], vp=9.0)        # voter == WALLET
    add_post(db, 1, "P", "carol", "I support this.")
    add_identity(db, "carol", WALLET.lower(), "high")
    seen = {}
    script = iter([NS(content=None, tool_calls=[NS(id="c1", function=NS(
                        name="search_forum", arguments='{"query": "why support"}'))]),
                   NS(content="DONE", tool_calls=None)])
    monkeypatch.setattr(agent, "generate_with_tools", lambda messages, tool_list: (next(script), "fake"))
    monkeypatch.setattr(tools, "retrieve", lambda *a, **k: [chunk("P")])
    monkeypatch.setattr(service, "generate", lambda messages: seen.update(prompt=messages[1]["content"]) or ("ok", "fake"))

    out = service.run_chat("Why did people support it?", "P")

    assert "by carol (voting power 9.0, voted For, wallet link: high)" in seen["prompt"]
    assert [c["id"] for c in out["chunks"]] == ["forum_post_P_1"]


def test_the_arguments_of_run_chat_reach_the_agent(monkeypatch):
    got = {}
    monkeypatch.setattr(service, "gather_evidence", lambda *a: got.update(args=a) or [])
    monkeypatch.setattr(service, "generate", lambda messages: ("ok", "fake"))
    on_lookup = object()

    service.run_chat("why?", "P", n_results=7, on_lookup=on_lookup)

    assert got["args"] == ("why?", "P", 7, on_lookup)


def test_a_question_without_evidence_still_reaches_the_writer(monkeypatch):
    """'What is a DAO?' needs no lookup; the writer answers from background (marked) or says it has no data."""
    seen = {}
    monkeypatch.setattr(service, "gather_evidence", lambda *a: [])
    monkeypatch.setattr(service, "generate", lambda messages: seen.update(prompt=messages[1]["content"]) or ("ok", "fake"))

    out = service.run_chat("What is a DAO?")

    assert out["answer"] == "ok" and out["chunks"] == [] and out["evidence"] == []
    assert "(no passage was found)" in seen["prompt"]


def test_lookups_say_which_search_we_ran_ourselves():
    evidence = [{"tool": "search_forum", "arguments": {"query": "q"}, "result": {"chunks": [{"id": "c"}]}, "automatic": True},
                {"tool": "dao_stats", "arguments": {}, "result": {"daos": []}}]
    first, second = service.lookups(evidence)
    assert first == {"tool": "search_forum", "arguments": {"query": "q"}, "result": {"passages_found": 1}, "automatic": True}
    assert "automatic" not in second


def test_lookups_summarise_searches_but_keep_other_results():
    evidence = [entry("search_forum", {"chunks": [chunk("P"), chunk("P", "dave")]}, query="why"),
                entry("search_forum", {"error": "No forum posts by 'x' in our data."}, query="why", author="x"),
                entry("dao_stats", {"daos": []})]
    assert service.lookups(evidence) == [
        {"tool": "search_forum", "arguments": {"query": "why"}, "result": {"passages_found": 2}},
        {"tool": "search_forum", "arguments": {"query": "why", "author": "x"},
         "result": {"error": "No forum posts by 'x' in our data."}},
        {"tool": "dao_stats", "arguments": {}, "result": {"daos": []}},
    ]


# ── providers ────────────────────────────────────────────────────────────────

def test_provider_list_is_exactly_the_providers_we_support():
    """Mistral was removed on purpose; a half-removed provider once broke every import of the chat."""
    assert [name for name, _ in llm.PROVIDERS] == ["groq", "gemini", "openrouter"]
    assert all(callable(fn) for _, fn in llm.PROVIDERS)
    assert not hasattr(llm, "call_mistral")
    assert [name for name, _ in llm.TOOL_PROVIDERS] == ["groq", "gemini", "groq-small", "openrouter"]   # all accept OpenAI-style tools


def test_generate_falls_back_to_the_next_provider(monkeypatch):
    def failing(messages):
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(llm, "PROVIDERS", [("first", failing), ("second", lambda m: "answer")])
    assert llm.generate([{"role": "user", "content": "hi"}]) == ("answer", "second")


class FakeClient:
    """Stands in for an OpenAI-style client; `outcome` is a reply or an exception to raise."""

    def __init__(self, outcome):
        self.chat = NS(completions=NS(create=self.create))
        self.outcome, self.calls = outcome, 0

    def create(self, **kwargs):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return NS(choices=[NS(message=self.outcome)])


def test_tool_calling_falls_back_to_the_next_provider_with_the_same_messages(monkeypatch):
    reply = NS(content=None, tool_calls=["a lookup request"])
    monkeypatch.setattr(llm, "TOOL_PROVIDERS", [("first", lambda: (FakeClient(RuntimeError("quota")), "m1")),
                                                ("second", lambda: (FakeClient(reply), "m2"))])
    assert llm.generate_with_tools([{"role": "user", "content": "hi"}], []) == (reply, "second")


def test_gemini_gets_the_lookups_as_plain_text_not_as_tool_calls():
    """Gemini answered 400 'Function call is missing a thought_signature' to tool calls written by Groq."""
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "How many voters?"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function",
                         "function": {"name": "list_proposals", "arguments": '{"order_by": "voters"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"proposals": [{"voters": 63845}]}'},
    ]
    flat = llm.flatten_tool_history(messages)
    assert [m["role"] for m in flat] == ["system", "user", "user"]
    assert "list_proposals" in flat[2]["content"] and "63845" in flat[2]["content"]
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in flat)
    assert llm.flatten_tool_history(messages[:2]) == messages[:2]                 # nothing to flatten yet


def test_only_gemini_is_sent_the_flattened_history(monkeypatch):
    sent = {}

    def client_for(name):
        def make():
            client = FakeClient(NS(content="DONE", tool_calls=None))
            create = client.create
            client.chat.completions.create = lambda **kw: sent.setdefault(name, kw["messages"]) and create(**kw)
            return client, "m"
        return make

    monkeypatch.setattr(llm, "TOOL_PROVIDERS", [("groq", lambda: (_ for _ in ()).throw(RuntimeError("down"))),
                                                ("gemini", client_for("gemini"))])
    history = [{"role": "user", "content": "q"},
               {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "c1", "content": "result"}]
    llm.generate_with_tools(history, [])
    assert not any(m["role"] == "tool" for m in sent["gemini"])


def test_the_agent_still_works_when_the_big_models_are_out_of_quota(monkeypatch):
    """Groq's 120b and Gemini's 20 requests a day ran out; the last tool provider is a separate quota."""
    reply = NS(content="DONE", tool_calls=None)
    out_of_quota = lambda: (FakeClient(RuntimeError("429 quota")), "m")
    monkeypatch.setattr(llm, "TOOL_PROVIDERS", [("groq", out_of_quota), ("gemini", out_of_quota),
                                                ("groq-small", lambda: (FakeClient(reply), "small"))])
    assert llm.generate_with_tools([{"role": "user", "content": "hi"}], []) == (reply, "groq-small")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    client, model = llm._tool_client_groq_small()
    assert model == "openai/gpt-oss-20b" and client.timeout == llm.LLM_TIMEOUT_SECONDS


def test_openrouter_models_are_current_and_the_agent_can_use_the_first(monkeypatch):
    """Three of four listed models stopped being free and 404'd silently; the list was re-tested."""
    assert llm.OPENROUTER_FREE_MODELS[0] == "nvidia/nemotron-3.5-super-vl:free"
    assert all(m.endswith(":free") for m in llm.OPENROUTER_FREE_MODELS) and len(llm.OPENROUTER_FREE_MODELS) >= 3
    for gone in ("z-ai/glm-5.2:free", "nvidia/nemotron-3-super-120b-a12b:free", "qwen/qwen3.8-27b:free"):
        assert gone not in llm.OPENROUTER_FREE_MODELS
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    client, model = llm._tool_client_openrouter()
    assert model == llm.OPENROUTER_FREE_MODELS[0] and client.timeout == llm.LLM_TIMEOUT_SECONDS


def test_the_openrouter_check_reports_models_that_stopped_being_free(monkeypatch, capsys):
    ours = llm.OPENROUTER_FREE_MODELS
    monkeypatch.setattr(llm, "openrouter_free_models", lambda: {ours[0]: True, ours[1]: False, "other/model:free": True})
    gone = llm.check_openrouter_models()
    out = capsys.readouterr().out
    assert gone == ours[2:]                                              # not in the free list any more
    assert "GONE" in out and "NO tools" in out and "other/model:free" in out


def test_no_provider_can_hang_for_minutes(monkeypatch):
    """A stalled request used to block one eval case for 28 minutes (the openai package waits 10)."""
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    for make in (llm._tool_client_groq, llm._tool_client_gemini):
        client, _model = make()
        assert client.timeout == llm.LLM_TIMEOUT_SECONDS <= 60
        assert client.max_retries <= 1


def test_a_short_rate_limit_is_waited_out_instead_of_falling_back(monkeypatch):
    """Groq: 'Please try again in 4.83s'. Falling back would burn Gemini's 20 requests a day."""
    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    attempts = iter([RuntimeError("Rate limit ... Please try again in 4.83s. Need more tokens?"), "answer"])

    def flaky(messages):
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(llm, "PROVIDERS", [("first", flaky), ("second", lambda m: "from second")])
    assert llm.generate([{"role": "user", "content": "hi"}]) == ("answer", "first")
    assert slept == [5.33]


def test_a_long_wait_or_another_error_is_not_retried(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    assert llm._retry_delay(RuntimeError("try again in 1m3.5s")) == 63.5
    assert llm._retry_delay(RuntimeError("quota exceeded")) is None

    def too_long(messages):
        raise RuntimeError("Please try again in 7m12.5s")

    monkeypatch.setattr(llm, "PROVIDERS", [("first", too_long), ("second", lambda m: "from second")])
    assert llm.generate([{"role": "user", "content": "hi"}]) == ("from second", "second")
    assert slept == []                                          # did not wait 7 minutes


# ── Where control goes next ───────────────────────────────────────────────────
# Stage 1 (the loop) is tested in tests/test_agent.py, the lookups in tests/test_tools.py,
# the writer's prompt in tests/test_prompt.py.
