# api/routes_sync.py
"""
DAO Governance Intelligence — Sync & Data Audit Endpoints
=========================================================

Endpoints to inspect collection dates, data freshness, gaps, and trigger
automated updates from Snapshot and Discourse.
"""

from fastapi import APIRouter, BackgroundTasks, Query
from db.schema import get_connection
from ingestion.sync_pipeline import (
    audit_collection_status,
    fetch_new_proposals,
    fetch_missing_votes,
    fetch_missing_forum_posts,
    sync_all,
)

router = APIRouter(prefix="/sync", tags=["Data Sync & Audit"])


@router.get("/status", summary="Audit collected data dates and missing records")
def get_sync_status():
    """
    Returns an audit of all governance data currently collected in the local database:
    - Date ranges of proposals, votes, and forum posts
    - Last fetched timestamps
    - Count of missing votes and missing forum discussions
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
    1. Fetches latest proposals from Snapshot GraphQL and updates active proposal states
    2. Fetches missing forum discussions for proposals with discussion URLs
    3. Fetches missing votes for proposals lacking voter records
    """
    conn = get_connection()
    result = sync_all(conn, proposals_first=limit, votes_proposals_limit=limit)
    conn.close()
    return {
        "message": "Data sync completed successfully",
        "details": {
            "proposals": result["proposals"],
            "forum_posts_added": result["forum_posts_added"],
            "votes": result["votes"],
        },
        "updated_status": result["current_status"]
    }
