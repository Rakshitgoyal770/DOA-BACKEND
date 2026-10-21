# features/chat/routes.py
"""
POST /chat   — RAG-powered Q&A over DAO governance data.

Request body:
  query       : str   — the user's question
  proposal_id : str   — optional; scopes retrieval to a single proposal
  n_results   : int   — number of chunks to retrieve (default 5)

Response:
  answer      : str   — LLM answer with [Source N] citations
  provider    : str   — which LLM answered (groq / gemini / openrouter / mistral)
  sources     : list  — retrieved chunks with metadata
  chunks_found: int   — how many chunks passed the distance threshold
  query       : str   — echoed back for traceability
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from features.chat.context import collect_facts, enrich_chunks
from features.chat.retrieval import retrieve
from features.chat.service import answer_question
from db.schema import get_connection

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
    source_type: str          # "proposal_body" | "forum_post"
    proposal_id: str | None
    author: str | None        # present for forum_post sources
    voting_power: float | None  # present when identity resolved
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


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse, summary="Ask a governance question")
def chat(req: ChatRequest):
    """
    Retrieves relevant chunks from the vector store (optionally scoped to a
    single proposal), builds a cited prompt, and returns the LLM's answer
    together with the source chunks that were used.

    Set `proposal_id` to restrict the context to one proposal — useful for
    deep-dive questions like "who argued against this and why?".
    Leave it null for cross-DAO or cross-proposal questions.
    """
    where_filter = {"proposal_id": req.proposal_id} if req.proposal_id else None

    chunks = retrieve(req.query, n_results=req.n_results, where=where_filter)

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=(
                "No relevant context found for this query. "
                "Try broadening the question or removing the proposal_id filter."
            )
        )

    conn = get_connection()
    try:
        enrich_chunks(conn, chunks)
        facts = collect_facts(conn, chunks)
    finally:
        conn.close()

    answer, provider = answer_question(req.query, chunks, facts)

    sources = [
        SourceChunk(
            id=c["id"],
            document=c["document"],
            source_type=c["metadata"].get("source_type", "unknown"),
            proposal_id=c["metadata"].get("proposal_id"),
            author=c["metadata"].get("author"),
            voting_power=c["sql"].get("voting_power", c["metadata"].get("voting_power")),
            distance=round(c["distance"], 4),
            wallet=c["sql"].get("wallet"),
            ens_name=c["sql"].get("ens_name"),
            link_confidence=c["sql"].get("link_confidence"),
            voted=c["sql"].get("voted"),
        )
        for c in chunks
    ]

    return ChatResponse(
        query=req.query,
        answer=answer,
        provider=provider,
        chunks_found=len(chunks),
        sources=sources,
        proposal_facts=facts,
    )
