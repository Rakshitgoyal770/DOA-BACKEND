# features/chat/service.py
"""
features/chat/service.py — The whole question-answering pipeline in one place.

WHAT THIS FILE DOES
    run_chat() answers one question in two stages and returns ONE answer:

      STAGE 1  gather_evidence   (features/chat/agent.py)
               the LLM chooses lookups, we run them on SQLite / ChromaDB
               (features/chat/tools.py): rankings, one proposal's numbers, a person's
               vote and posts, forum passages with their authors' wallets and votes.
               It returns the EVIDENCE; it never writes the answer.
      STAGE 2  answer_question   (features/chat/prompt.py + llm.py)
               build_prompt turns the evidence into the writer's prompt (the answer rules:
               citations, [Background] marking, advice mode); generate asks the LLM,
               falling back across providers.

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

from features.chat.agent import gather_evidence
from features.chat.llm import generate
from features.chat.prompt import build_prompt, split_evidence


def answer_question(query: str, evidence: list[dict]) -> tuple[str, str]:
    """
    Stage 2: build the prompt and ask the LLM. Returns (answer, provider name).

    Parameters (where they come from):
        query    - the question, passed through from run_chat().
        evidence - gather_evidence() output (from run_chat()).
    Kept as its own function so tests can replace the LLM call alone.
    """
    return generate(build_prompt(query, evidence))


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
        {"answer": str, "provider": str, "chunks": [...], "evidence": [...]}
    "chunks" are the forum / proposal passages the answer was built from (best first),
    "evidence" is everything the agent looked up (see lookups() for a short form).
    A question that needs no lookup ("what is a DAO?") still gets an answer: the writer
    uses general background, marked [Background], or says it has no data.

    Parameters (where they come from):
        query       - ChatRequest.query (features/chat/routes.py) or a golden-dataset
                      question (eval/eval_harness.py).
        proposal_id - ChatRequest.proposal_id / the golden case's proposal_id.
        n_results   - ChatRequest.n_results (1-20, default 5).
        on_lookup   - optional; called with each lookup as it runs (the terminal chat shows it).
    """
    evidence = gather_evidence(query, proposal_id, n_results, on_lookup)
    answer, provider = answer_question(query, evidence)
    return {"answer": answer, "provider": provider,
            "chunks": split_evidence(evidence)[0], "evidence": evidence}


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller:
#   features/chat/routes.py  -> builds the ChatResponse JSON for the client
#   features/chat/cli.py     -> prints the answer
#   eval/eval_harness.py     -> scores the answer and the retrieved chunk ids
# If every LLM provider fails (either stage): RuntimeError; the API returns HTTP 500 and
#   the eval records the case as an "error" and continues.
# To follow the data, read next: features/chat/agent.py (stage 1), then tools.py.
