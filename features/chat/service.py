# features/chat/service.py
"""
features/chat/service.py — The whole question-answering pipeline in one place.

WHAT THIS FILE DOES
    run_chat() answers one question, step by step:
      1. retrieve       find the text chunks closest to the question  (ChromaDB)
      2. enrich_chunks  add each forum author's wallet / vote          (SQLite)
      3. collect_facts  add each proposal's result and numbers         (SQLite)
      4. build_prompt   write the instructions + facts + sources       (text)
      5. generate       ask the LLM, falling back across providers     (network)
    Both the API (POST /chat) and the evaluation (eval/eval_harness.py) call
    run_chat(), so the evaluation always measures the exact pipeline users get.

WHERE IT SITS
    features/chat/routes.py (POST /chat)  ─┐
    eval/eval_harness.py                   ├─> THIS FILE ─> retrieval.py, context.py,
                                           ┘                prompt.py, llm.py

INPUTS
    query       - the user's question (ChatRequest.query, or a golden-dataset question)
    proposal_id - optional; limits the search to one proposal's chunks
    n_results   - how many chunks to fetch before the distance filter (default 5)
"""

from db.schema import get_connection
from features.chat.context import collect_facts, enrich_chunks
from features.chat.llm import generate
from features.chat.prompt import build_prompt
from features.chat.retrieval import retrieve


def answer_question(query: str, chunks: list[dict], facts: list[dict] | None = None) -> tuple[str, str]:
    """
    Steps 4-5: build the prompt and ask the LLM. Returns (answer, provider name).

    Parameters (where they come from):
        query  - the question, passed through from run_chat().
        chunks - retrieved chunks after enrich_chunks() (from run_chat()).
        facts  - collect_facts() output (from run_chat()).
    Kept as its own function so tests can replace the LLM call alone.
    """
    return generate(build_prompt(query, chunks, facts))


def run_chat(query: str, proposal_id: str | None = None, n_results: int = 5) -> dict:
    """
    Answer one question. Returns a dict:
        {"chunks": [...], "facts": [...], "answer": str | None, "provider": str | None}
    "answer" is None when no chunk was close enough; the LLM is then NOT called
    (the route turns that into HTTP 404, the eval skips the case).

    Parameters (where they come from):
        query       - ChatRequest.query (features/chat/routes.py) or a golden-dataset
                      question (eval/eval_harness.py).
        proposal_id - ChatRequest.proposal_id / the golden case's proposal_id.
        n_results   - ChatRequest.n_results (1-20, default 5).
    """
    where = {"proposal_id": proposal_id} if proposal_id else None
    chunks = retrieve(query, n_results=n_results, where=where)
    if not chunks:
        return {"chunks": [], "facts": [], "answer": None, "provider": None}

    conn = get_connection()
    try:
        enrich_chunks(conn, chunks)
        facts = collect_facts(conn, chunks)
    finally:
        conn.close()

    answer, provider = answer_question(query, chunks, facts)
    return {"chunks": chunks, "facts": facts, "answer": answer, "provider": provider}


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller:
#   features/chat/routes.py  -> builds the ChatResponse JSON for the client
#   eval/eval_harness.py     -> scores the answer and the retrieved chunk ids
# If every LLM provider fails: generate() raises RuntimeError; the API returns
#   HTTP 500 and the eval stops with that error.
# To follow the data, read next: features/chat/retrieval.py (step 1).
