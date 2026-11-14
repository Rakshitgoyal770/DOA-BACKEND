# features/chat/service.py
"""
features/chat/service.py — The whole question-answering pipeline in one place.

WHAT THIS FILE DOES
    run_chat() answers one question in three steps and returns ONE answer:

      STAGE 1  gather            the EVIDENCE, from SQLite / ChromaDB (features/chat/tools.py):
               rankings, one proposal's numbers, a person's vote and posts, passages with their
               authors' wallets and votes. It never writes the answer. Two ways to gather:
                 "planned" (default)  features/chat/planner.py: the question is understood once
                                      (rules, or one model call), then a fixed set of lookups and
                                      searches runs for that kind of question.
                 "agent"              features/chat/agent.py: the model picks lookups in a loop.
               The planned way falls back to the agent when the question cannot be understood.
               Choose with the environment variable CHAT_PIPELINE=planned|agent (so the same
               evaluation can be run on both).
      STAGE 2  answer_question   (features/chat/prompt.py + llm.py)
               build_prompt turns the evidence into the writer's prompt (the answer rules:
               citations, [Background] marking, advice mode); generate asks the LLM,
               falling back across providers.
      STEP 3   check_and_repair  (features/chat/citations.py)
               the citations in the answer are checked against the evidence; an answer citing a
               source that was never given is rewritten once, then stripped of the bad markers.

    Both the API (POST /chat), the terminal chat (features/chat/cli.py) and the evaluation
    (eval/eval_harness.py) call run_chat(), so the evaluation measures the exact pipeline
    users get.

WHERE IT SITS
    features/chat/routes.py (POST /chat)  ─┐
    features/chat/cli.py                   ├─> THIS FILE ─> agent.py (tools.py), prompt.py, llm.py
    eval/eval_harness.py                   ┘

INPUTS
    query       - the user's question (ChatRequest.query, or a golden-dataset question)
    proposal_id - optional; the proposal the user selected (lookups use it by default)
    n_results   - passages per forum search (default 5)
"""

import logging
import os

from features.chat.agent import gather_evidence
from features.chat.citations import check_citations, correction_request, strip_invalid
from features.chat.llm import generate
from features.chat.planner import PlanError, gather_planned
from features.chat.prompt import build_prompt, split_evidence

logger = logging.getLogger(__name__)


def pipeline() -> str:
    """"planned" (default) or "agent": how stage 1 gathers the evidence (environment variable CHAT_PIPELINE)."""
    return "agent" if os.environ.get("CHAT_PIPELINE", "planned").strip().lower() == "agent" else "planned"


def gather(query: str, proposal_id: str | None, n_results: int, on_lookup=None) -> tuple[list[dict], dict]:
    """
    Stage 1: (evidence, info). info says how it was gathered:
    {"mode": "planned", "kind": ..., "dao": ..., ...} (the plan) or {"mode": "agent"}, plus
    "fallback_reason" when the planned way gave up and the agent ran instead.

    A planned run that fails for any reason except "every model provider is down" falls back to the
    agent, so a bug in the planner never leaves a question unanswered. When every provider is down
    the error is raised: the agent would only try the same providers again.

    Parameters (where they come from): run_chat's.
    """
    reason = None
    if pipeline() == "planned":
        try:
            evidence, plan = gather_planned(query, proposal_id, n_results, on_lookup)
            return evidence, {"mode": "planned", **plan.model_dump(exclude_none=True)}
        except RuntimeError as error:
            if str(error).startswith("All providers failed"):
                raise
            reason = f"{type(error).__name__}: {error}"
        except PlanError as error:
            reason = f"PlanError: {error}"
        except Exception as error:                      # a bug in the planner must not stop the answer
            logger.exception("planned evidence gathering failed, using the agent")
            reason = f"{type(error).__name__}: {error}"
    return (gather_evidence(query, proposal_id, n_results, on_lookup),
            {"mode": "agent", **({"fallback_reason": reason} if reason else {})})


def answer_question(query: str, evidence: list[dict]) -> tuple[str, str]:
    """
    Stage 2: build the prompt and ask the LLM. Returns (answer, provider name).

    Parameters (where they come from):
        query    - the question, passed through from run_chat().
        evidence - gather_evidence() output (from run_chat()).
    Kept as its own function so tests can replace the LLM call alone.
    """
    return generate(build_prompt(query, evidence))


def check_and_repair(query: str, evidence: list[dict], answer: str, provider: str) -> tuple[str, str, dict]:
    """
    Step 3: (answer, provider, check). The answer's citations are checked (features/chat/citations.py).
    If it cites a source that was not given, the writer is asked once to rewrite it; if the rewrite
    still cites nothing real, the bad markers are removed. check["repaired"] says which happened
    ("rewritten" or "stripped"); it is absent when the answer was fine.

    Parameters (where they come from): run_chat's query and evidence, and the writer's answer and
    provider name.
    """
    chunks, entries = split_evidence(evidence)
    messages = build_prompt(query, evidence)
    count, has_facts, seen = len(chunks), bool(entries), messages[1]["content"]
    check = check_citations(answer, count, has_facts, seen)
    if check["ok"]:
        return answer, provider, check
    try:
        again, again_provider = generate(messages + [{"role": "assistant", "content": answer},
                                                     {"role": "user", "content": correction_request(check, count)}])
    except RuntimeError:                                 # no provider left for the rewrite: strip instead
        again = None
    if again:
        second = check_citations(again, count, has_facts, seen)
        if second["ok"]:
            return again, again_provider, {**second, "repaired": "rewritten"}
        answer, provider = again, again_provider
    cleaned = strip_invalid(answer, count, has_facts)
    return cleaned, provider, {**check_citations(cleaned, count, has_facts, seen), "repaired": "stripped"}


def lookups(evidence: list[dict]) -> list[dict]:
    """
    What the agent looked up, for the API response and the terminal chat:
    [{"tool", "arguments", "result"}]. A forum search shows only how many passages it
    found, because the passages themselves are returned as "sources".

    Parameter (where it comes from): run_chat()["evidence"].
    """
    return [{"tool": e["tool"], "arguments": e["arguments"],
             "result": ({"passages_found": len(e["result"].get("chunks", []))}
                        if e["tool"] == "search_forum" and "chunks" in e["result"] else e["result"]),
             **({"automatic": True} if e.get("automatic") else {})}      # a search we ran, not the model
            for e in evidence]


def run_chat(query: str, proposal_id: str | None = None, n_results: int = 5, on_lookup=None) -> dict:
    """
    Answer one question. Returns a dict:
        {"answer": str, "provider": str, "chunks": [...], "evidence": [...], "plan": {...}, "citations": {...}}
    "chunks" are the forum / proposal passages the answer was built from (best first),
    "evidence" is everything that was looked up (see lookups() for a short form), "plan" how it was
    gathered (gather()) and "citations" the result of the citation check (check_and_repair()).
    A question that needs no lookup ("what is a DAO?") still gets an answer: the writer
    uses general background, marked [Background], or says it has no data.

    Parameters (where they come from):
        query       - ChatRequest.query (features/chat/routes.py) or a golden-dataset
                      question (eval/eval_harness.py).
        proposal_id - ChatRequest.proposal_id / the golden case's proposal_id.
        n_results   - ChatRequest.n_results (1-20, default 5).
        on_lookup   - optional; called with each lookup as it runs (the terminal chat shows it).
    """
    evidence, plan = gather(query, proposal_id, n_results, on_lookup)
    answer, provider = answer_question(query, evidence)
    answer, provider, citations = check_and_repair(query, evidence, answer, provider)
    return {"answer": answer, "provider": provider, "chunks": split_evidence(evidence)[0],
            "evidence": evidence, "plan": plan, "citations": citations}


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller:
#   features/chat/routes.py  -> builds the ChatResponse JSON for the client
#   features/chat/cli.py     -> prints the answer
#   eval/eval_harness.py     -> scores the answer and the retrieved chunk ids
# If every LLM provider fails (either stage): RuntimeError; the API returns HTTP 500 and
#   the eval records the case as an "error" and continues.
# To follow the data, read next: features/chat/planner.py (stage 1), then tools.py; features/chat/agent.py
#   is the fallback.
