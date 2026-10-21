# features/sync/runner.py
"""
Runs the data sync end to end and exposes the command line.

    python -m features.sync.runner --check
    python -m features.sync.runner --sync-all
    python -m features.sync.runner --fetch-votes --limit 10
    python -m features.sync.runner --fetch-all-votes --limit 200 [--space ens.eth]
"""

import argparse
import logging
from typing import Any, Dict

from db.schema import get_connection
from features.forum.fetch import fetch_missing_forum_posts
from features.proposals.fetch import fetch_new_proposals
from features.sync.audit import audit_collection_status, print_audit_report
from features.votes.fetch import fetch_all_votes, fetch_missing_votes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sync_all(conn, proposals_first: int = 10, votes_proposals_limit: int = 10) -> Dict[str, Any]:
    """
    Executes a complete sync:
    1. Fetches new proposals & updates active ones
    2. Fetches missing forum discussions
    3. Fetches missing votes
    4. Audits updated status
    """
    logger.info("=== STARTING FULL DATA SYNC ===")
    prop_res = fetch_new_proposals(conn, first_per_dao=proposals_first)
    forum_res = fetch_missing_forum_posts(conn, limit=20)
    vote_res = fetch_missing_votes(conn, max_proposals=votes_proposals_limit, votes_per_prop=500)
    audit = audit_collection_status(conn)
    logger.info("=== SYNC COMPLETED SUCCESSFULLY ===")
    return {
        "proposals": prop_res,
        "forum_posts_added": forum_res,
        "votes": vote_res,
        "current_status": audit
    }


# ── CLI Interface ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAO Governance Data Audit & Sync")
    parser.add_argument("--check", action="store_true", help="Print audit report of collected dates and missing items")
    parser.add_argument("--sync-all", action="store_true", help="Fetch new proposals, missing forum posts, and missing votes")
    parser.add_argument("--fetch-proposals", action="store_true", help="Fetch new proposals from Snapshot")
    parser.add_argument("--fetch-votes", action="store_true", help="Fetch missing votes for proposals")
    parser.add_argument("--fetch-all-votes", action="store_true", help="Fetch EVERY vote for incomplete proposals (no 500 cap)")
    parser.add_argument("--space", default=None, help="Limit --fetch-all-votes to one DAO space id")
    parser.add_argument("--fetch-forum", action="store_true", help="Fetch missing forum posts")
    parser.add_argument("--limit", type=int, default=10, help="Batch limit for votes or proposals (default: 10)")

    args = parser.parse_args()
    conn = get_connection()

    if args.sync_all:
        res = sync_all(conn, proposals_first=args.limit, votes_proposals_limit=args.limit)
        print_audit_report(res["current_status"])
    elif args.fetch_proposals:
        res = fetch_new_proposals(conn, first_per_dao=args.limit)
        print(f"Proposals sync complete: {res}")
    elif args.fetch_all_votes:
        res = fetch_all_votes(conn, max_proposals=args.limit, space_id=args.space)
        print(f"Full votes sync complete: {res}")
    elif args.fetch_votes:
        res = fetch_missing_votes(conn, max_proposals=args.limit)
        print(f"Votes sync complete: {res}")
    elif args.fetch_forum:
        res = fetch_missing_forum_posts(conn, limit=args.limit)
        print(f"Forum sync complete: {res} posts ingested")
    else:
        # Default action is check
        audit = audit_collection_status(conn)
        print_audit_report(audit)

    conn.close()
