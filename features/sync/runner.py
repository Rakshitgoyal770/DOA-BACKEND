# features/sync/runner.py
"""
Runs the data sync end to end and exposes the command line.

    python -m features.sync.runner --check                       # audit only, no downloads
    python -m features.sync.runner --sync-all                    # proposals, forum, votes
    python -m features.sync.runner --fetch-votes --limit 200 [--space ens.eth]
    python -m features.sync.runner --fetch-forum --limit 200     # every post of every thread

Votes are always fetched completely (every vote, no cap). `--fetch-all-votes`
is kept as an alias of `--fetch-votes` for older scripts.
"""

import argparse
import logging
from typing import Any, Dict

from db.schema import get_connection
from features.forum.fetch import fetch_forum_threads
from features.proposals.fetch import sync_proposals
from features.sync.audit import audit_collection_status, print_audit_report
from features.votes.fetch import fetch_all_votes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def sync_all(conn, votes_proposals_limit: int = 10, initial_proposals_per_dao: int = 20) -> Dict[str, Any]:
    """
    Executes a complete sync:
    1. Re-reads every unfinished proposal by id, then adds every proposal
       published since the newest one stored (no 'latest N' window)
    2. Fetches forum threads that are new, incomplete, failed, or recently active
       (every post, not just Discourse's first page of 20)
    3. Fetches ALL votes for up to `votes_proposals_limit` proposals whose
       votes are missing or partial (active proposals gain votes, so they
       come back here until they close)
    4. Audits updated status, including vote completeness
    """
    logger.info("=== STARTING FULL DATA SYNC ===")
    prop_res = sync_proposals(conn, initial_per_dao=initial_proposals_per_dao)
    forum_res = fetch_forum_threads(conn, limit=20)
    vote_res = fetch_all_votes(conn, max_proposals=votes_proposals_limit)
    audit = audit_collection_status(conn)
    logger.info("=== SYNC COMPLETED SUCCESSFULLY ===")
    return {
        "proposals": prop_res,
        "forum": forum_res,
        "votes": vote_res,
        "current_status": audit
    }


# ── CLI Interface ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAO Governance Data Audit & Sync")
    parser.add_argument("--check", action="store_true", help="Print audit report of collected dates and missing items")
    parser.add_argument("--sync-all", action="store_true", help="Fetch new proposals, missing forum posts, and missing votes")
    parser.add_argument("--fetch-proposals", action="store_true", help="Refresh unfinished proposals and add newly published ones")
    parser.add_argument("--fetch-votes", "--fetch-all-votes", dest="fetch_votes", action="store_true",
                        help="Fetch every vote for proposals whose votes are missing or partial")
    parser.add_argument("--space", default=None, help="Limit --fetch-votes to one DAO space id")
    parser.add_argument("--fetch-forum", action="store_true", help="Fetch every post of forum threads that are new, incomplete or recent")
    parser.add_argument("--limit", type=int, default=10, help="Max proposals (votes) or threads (forum) to process per run (default: 10)")

    args = parser.parse_args()
    conn = get_connection()

    if args.sync_all:
        res = sync_all(conn, votes_proposals_limit=args.limit)
        print_audit_report(res["current_status"])
    elif args.fetch_proposals:
        res = sync_proposals(conn)
        print(f"Proposals sync complete: {res}")
    elif args.fetch_votes:
        res = fetch_all_votes(conn, max_proposals=args.limit, space_id=args.space)
        print(f"Votes sync complete: {res}")
    elif args.fetch_forum:
        res = fetch_forum_threads(conn, limit=args.limit)
        print(f"Forum sync complete: {res}")
    else:
        # Default action is check
        audit = audit_collection_status(conn)
        print_audit_report(audit)

    conn.close()
