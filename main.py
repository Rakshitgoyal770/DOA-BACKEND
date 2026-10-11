# main.py
"""
DAO Governance Intelligence — FastAPI Backend
=============================================

Runs a RAG-powered API over governance data ingested from Snapshot (on-chain
votes) and Discourse (forum discussions) for 5 major DAOs.

Start server:
    uvicorn main:app --reload --port 8000

Interactive API docs (auto-generated):
    http://127.0.0.1:8000/docs
    http://127.0.0.1:8000/redoc

Key findings surfaced by this system (measured on real data):
  - Fewer than 1.5% of voters ever post in governance forums
  - Median top-4 voter concentration: ~84% of total voting power
  - 100% of 100 ingested proposals have linked forum discussions
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_chat import router as chat_router
from api.routes_dao import router as dao_router
from api.routes_proposal import router as proposal_router
from db.schema import init_db


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DAO Governance Intelligence API",
    description=(
        "RAG-powered Q&A and analytics over DAO governance data. "
        "Combines on-chain votes (Snapshot) with off-chain forum discussions (Discourse) "
        "to surface who voted, what they said, and who stayed silent. \n\n"
        "**Key Stats (measured on real data):**\n"
        "- < 1.5% of voters ever post in governance forums\n"
        "- Median top-4 voter concentration: ~84% of total voting power\n"
        "- 5 major DAOs covered: Arbitrum, Aave, Optimism, Uniswap, ENS\n\n"
        "**Architecture:** SQLite (structured data) + ChromaDB (vector store) + "
        "Multi-provider LLM fallback (Groq → Gemini → OpenRouter → Mistral)"
    ),
    version="0.1.0",
    contact={
        "name": "DOA-BACKEND",
        "url": "https://github.com/Rakshitgoyal770/DOA-BACKEND",
    },
    license_info={"name": "MIT"},
)

# Allow local frontend / Postman / curl during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(chat_router)
app.include_router(dao_router)
app.include_router(proposal_router)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    """Ensure DB schema is initialised before accepting requests."""
    init_db()
    print("[OK] Database ready")
    print("[OK] API started - docs at http://127.0.0.1:8000/docs")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Health check")
def root():
    """Returns service status and available endpoints."""
    return {
        "status": "ok",
        "service": "DAO Governance Intelligence API",
        "version": "0.1.0",
        "endpoints": {
            "POST /chat": "Ask a natural-language governance question",
            "GET  /daos": "List all 5 curated DAOs with stats",
            "GET  /daos/{space_id}": "DAO detail with top proposals",
            "GET  /proposals": "List proposals (filter by space_id, state)",
            "GET  /proposals/{id}": "Full proposal detail",
            "GET  /proposals/{id}/concentration": "Whale concentration analysis",
        },
        "docs": "http://127.0.0.1:8000/docs",
    }
