# features/sync/routes.py
"""
DAO Governance Intelligence — Sync & Data Audit Endpoints
=========================================================

Endpoints to inspect collection dates, data freshness, gaps, and trigger
automated updates from Snapshot and Discourse.
"""

from fastapi import APIRouter, BackgroundTasks, Query
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
    - Count of missing votes and missing forum discussions
    - Vote completeness per proposal (stored vs. Snapshot's count)
    """
    conn = get_connection()
    status = audit_collection_status(conn)
    conn.close()
    return status


@router.post("/run", summary="Trigger automated data sync")
def run_sync(
    limit: int = Query(default=10, ge=1, le=50, description="Number of proposals/votes to process per batch"),
    background_tasks: BackgroundTasks = None
):
    """
    Triggers an automated sync:
    1. Re-reads unfinished proposals by id and adds every newly published proposal
    2. Fetches every post of forum threads that are new, incomplete or recently active
    3. Fetches every vote for up to `limit` proposals whose votes are missing or
       partial (no per-proposal cap; large proposals can take a while)
    """
    conn = get_connection()
    result = sync_all(conn, votes_proposals_limit=limit)
    conn.close()
    return {
        "message": "Data sync completed successfully",
        "details": {
            "proposals": result["proposals"],
            "forum": result["forum"],
            "votes": result["votes"],
        },
        "updated_status": result["current_status"]
    }
