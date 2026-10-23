# main.py
"""
main.py — Creates the web API and connects every feature to it.

WHAT THIS FILE DOES
    Builds the FastAPI app, allows browser access (CORS), registers one router
    per feature, makes sure the database schema exists at startup, and answers
    the health check at "/". No business logic lives here.

START THE SERVER
    uvicorn main:app --reload --port 8000
    Interactive API docs: http://127.0.0.1:8000/docs  (and /redoc)

THE FEATURES (each router lives in features/<name>/routes.py)
    /daos         DAO summaries               features/daos/
    /proposals    proposals, whale reports    features/proposals/
    /chat         RAG question answering      features/chat/
    /sync         data audit and sync         features/sync/
    /identities   forum user <-> wallet links features/identity/

HOW A REQUEST FLOWS
    client -> this app -> the matching router -> its service / metrics code -> SQLite
    (/chat also goes through ChromaDB and an LLM; /sync/run also calls Snapshot and Discourse)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.schema import init_db
from features.chat.routes import router as chat_router
from features.daos.routes import router as dao_router
from features.identity.routes import router as identity_router
from features.proposals.routes import router as proposal_router
from features.sync.routes import router as sync_router


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DAO Governance Intelligence API",
    description=(
        "RAG-powered Q&A and analytics over DAO governance data. "
        "Combines on-chain votes (Snapshot) with off-chain forum discussions (Discourse) "
        "to surface who voted, what they said, and who stayed silent.\n\n"
        "- 5 DAOs: Arbitrum, Aave, Optimism, Uniswap, ENS — every vote and every forum post "
        "of the stored proposals\n"
        "- Measured findings and their scope: see the project README\n\n"
        "**Architecture:** SQLite (structured data) + ChromaDB (vector store) + "
        "multi-provider LLM fallback (Groq → Gemini → OpenRouter)"
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
app.include_router(sync_router)
app.include_router(identity_router)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    """Create / upgrade the database schema before accepting requests (db/schema.py)."""
    init_db()
    print("[OK] Database ready")
    print("[OK] API started - docs at http://127.0.0.1:8000/docs")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Health check")
def root():
    """Service status and every registered endpoint. The list is read from the
    OpenAPI schema (the same data /docs shows), so it can never go out of date."""
    endpoints = {
        f"{method.upper():<4} {path}": operation.get("summary", "")
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
    }
    return {
        "status": "ok",
        "service": "DAO Governance Intelligence API",
        "version": "0.1.0",
        "endpoints": endpoints,
        "docs": "http://127.0.0.1:8000/docs",
    }


# ── Where control goes next ───────────────────────────────────────────────────
# Every request is handed to the router whose prefix matches; start reading at
# that feature's routes.py (e.g. features/chat/routes.py for POST /chat).
# If the path matches no router: FastAPI answers 404 itself.
