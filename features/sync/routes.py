# features/sync/routes.py
"""
features/sync/routes.py — The /sync HTTP endpoints: data audit and triggering a sync.

WHAT THIS FILE DOES
    GET  /sync/status   what data we have, how fresh it is, and what is incomplete
    POST /sync/run      run the full sync now (proposals, forum, votes) and return
                        what changed plus the new audit
    HTTP layer only: the work is in features/sync/audit.py and features/sync/runner.py.

WHERE IT SITS
    client --HTTP--> main.py (router registered there) --> THIS FILE
          --> features/sync/audit.py   (status)
          --> features/sync/runner.py  (run) --> proposals / forum / votes fetchers

INPUTS
    POST /sync/run ?limit=  (1-50, default 10): incomplete proposals to fetch votes for.
"""

from fastapi import APIRouter, Query

from db.schema import get_connection
from features.sync.audit import audit_collection_status
from features.sync.runner import sync_all

router = APIRouter(prefix="/sync", tags=["Data Sync & Audit"])


@router.get("/status", summary="Audit collected data dates and missing records")
def get_sync_status():
    """
    Returns an audit of all governance data currently collected in the local database:
    - Date ranges of proposals, votes, and forum posts
    - Last fetched timestamps
    - Vote completeness per proposal (stored vs. Snapshot's count)
    - Forum completeness per thread (stored vs. what Discourse listed)
    """
    conn = get_connection()
    try:
        return audit_collection_status(conn)
    finally:
        conn.close()


@router.post("/run", summary="Trigger automated data sync")
def run_sync(
    limit: int = Query(default=10, ge=1, le=50, description="Incomplete proposals to fetch votes for in this run"),
):
    """
    Runs the full sync and waits for it (large proposals can take a while):
    1. Refreshes DAO rows and unfinished proposals, and adds newly published ones
    2. Fetches every post of forum threads that are new, incomplete or recently active
    3. Fetches every vote for up to `limit` proposals whose votes are missing or partial
    """
    conn = get_connection()
    try:
        result = sync_all(conn, votes_proposals_limit=limit)
    finally:
        conn.close()
    return {
        "message": "Data sync finished",
        "details": {
            "proposals": result["proposals"],
            "forum": result["forum"],
            "votes": result["votes"],
        },
        "updated_status": result["current_status"],
    }


# ── Where control goes next ───────────────────────────────────────────────────
# GET /sync/status: features/sync/audit.py builds the report; then the response is sent.
# POST /sync/run:   features/sync/runner.py sync_all() does the work; then the response is sent.
# If one DAO / thread / proposal fails during a run: it appears in that step's
#   "failed" list and the audit; the endpoint itself still answers 200.
# After a run, new posts are not searchable in /chat until the index is synced
#   (python -m vector.embedding).
