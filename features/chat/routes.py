# features/chat/routes.py
"""
features/chat/routes.py — The POST /chat HTTP endpoint.

WHAT THIS FILE DOES
    Accepts a question, runs the chat pipeline (features/chat/service.py
    run_chat), and returns the answer together with the sources it used and
    the database facts that were put in the prompt. HTTP layer only: no search,
    SQL or LLM code lives here.

WHERE IT SITS
    client --HTTP--> main.py (router registered there) --> THIS FILE
          --> features/chat/service.py run_chat --> retrieval / context / prompt / llm

INPUTS (the JSON request body, validated by ChatRequest)
    query       : str  — the question (3-2000 characters)
    proposal_id : str  — optional; search only this proposal's chunks
    n_results   : int  — chunks to retrieve before filtering (1-20, default 5)

OUTPUT (ChatResponse)
    answer, provider (which LLM answered), chunks_found, sources (each chunk with
    author, wallet, voting power, distance), proposal_facts (the SQL facts used).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from features.chat.service import run_chat

router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Request / Response schemas ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000,
                       description="Natural-language question about DAO governance")
    proposal_id: str | None = Field(
        default=None,
        description="Snapshot proposal ID (0x...) — scopes retrieval to one proposal"
    )
    n_results: int = Field(default=5, ge=1, le=20,
                           description="Number of chunks to retrieve before filtering")


class SourceChunk(BaseModel):
    id: str
    document: str
    source_type: str                    # "proposal_body" | "forum_post"
    proposal_id: str | None
    author: str | None                  # present for forum_post sources
    voting_power: float | None          # present when the author's wallet voted on it
    distance: float
    wallet: str | None = None           # linked wallet for forum_post sources
    ens_name: str | None = None
    link_confidence: str | None = None  # certain | high | medium | low
    voted: str | None = None            # how the author's wallet voted on this proposal


class ChatResponse(BaseModel):
    query: str
    answer: str
    provider: str
    chunks_found: int
    sources: list[SourceChunk]
    proposal_facts: list[dict] = []     # SQL facts for the proposals behind the sources


def _source(c: dict) -> SourceChunk:
    """
    One retrieved chunk as a SourceChunk for the response.

    Parameter (where it comes from):
        c - a chunk from run_chat()["chunks"]: retrieval fields + "sql" added by
            features/chat/context.py enrich_chunks.
    """
    meta, sql = c["metadata"], c["sql"]
    return SourceChunk(
        id=c["id"],
        document=c["document"],
        source_type=meta.get("source_type", "unknown"),
        proposal_id=meta.get("proposal_id"),
        author=meta.get("author"),
        voting_power=sql.get("voting_power", meta.get("voting_power")),
        distance=round(c["distance"], 4),
        wallet=sql.get("wallet"),
        ens_name=sql.get("ens_name"),
        link_confidence=sql.get("link_confidence"),
        voted=sql.get("voted"),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse, summary="Ask a governance question")
def chat(req: ChatRequest):
    """
    Retrieves relevant chunks (optionally scoped to one proposal), adds the
    database facts, builds a cited prompt, and returns the LLM's answer with
    the sources that were used.

    Set `proposal_id` for deep-dive questions about one proposal
    ("who argued against this and why?"); leave it null for cross-DAO questions.
    """
    result = run_chat(req.query, req.proposal_id, req.n_results)
    if result["answer"] is None:
        raise HTTPException(
            status_code=404,
            detail=("No relevant context found for this query. "
                    "Try broadening the question or removing the proposal_id filter."),
        )
    return ChatResponse(
        query=req.query,
        answer=result["answer"],
        provider=result["provider"],
        chunks_found=len(result["chunks"]),
        sources=[_source(c) for c in result["chunks"]],
        proposal_facts=result["facts"],
    )


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/service.py — run_chat() does the actual work.
# After it returns, FastAPI sends ChatResponse as JSON and the request ends.
# If no chunk is close enough: HTTP 404 (the LLM is never called).
# If the request body is invalid (e.g. query shorter than 3 characters):
#   FastAPI answers 422 before this code runs.
# If every LLM provider fails: run_chat raises and the client gets HTTP 500.
