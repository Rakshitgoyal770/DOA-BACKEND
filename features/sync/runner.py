# features/sync/runner.py
"""
features/sync/runner.py — Runs the data sync end to end, and the sync command line.

WHAT THIS FILE DOES
    sync_all() brings the database up to date with the outside world, in the
    order the data depends on each other:
        1. proposals  features/proposals/fetch.py  sync_proposals
                      (DAO rows, unfinished proposals by id, newly published ones)
        2. forum      features/forum/fetch.py      fetch_forum_threads
                      (needs each proposal's discussion link from step 1)
        3. votes      features/votes/fetch.py      fetch_all_votes
                      (needs each proposal's votes_count from step 1)
        4. audit      features/sync/audit.py       audit_collection_status
                      (reports what is complete afterwards)

COMMAND LINE
    python -m features.sync.runner --check                       # audit only, no downloads
    python -m features.sync.runner --sync-all [--limit 10]       # steps 1-4
    python -m features.sync.runner --fetch-proposals             # step 1 only
    python -m features.sync.runner --fetch-forum --limit 200     # step 2 only (backfill)
    python -m features.sync.runner --fetch-votes --limit 200 [--space ens.eth]   # step 3 only
    (--fetch-all-votes is an alias of --fetch-votes for older scripts.)

WHERE IT SITS
    POST /sync/run (features/sync/routes.py) ──┐
    the command line above                     ├─> THIS FILE ─> the four modules above
                                               ┘
    Afterwards (not done here, see README "Keeping the Data Fresh"):
        python -m features.identity.runner --upgrade   then   python -m vector.embedding
"""

import argparse
import logging
from typing import Any, Dict

from db.schema import get_connection
from features.forum.fetch import fetch_forum_threads
from features.proposals.fetch import sync_proposals
from features.sync.audit import audit_collection_status, print_audit_report
from features.votes.fetch import fetch_all_votes

logger = logging.getLogger(__name__)

FORUM_THREADS_PER_SYNC = 20   # forum threads checked per sync_all run


def sync_all(conn, votes_proposals_limit: int = 10, initial_proposals_per_dao: int = 20) -> Dict[str, Any]:
    """
    Steps 1-4 above. Returns {"proposals", "forum", "votes", "current_status"}.

    Parameters (where they come from):
        conn                      - opened by run_sync() in features/sync/routes.py
                                    (POST /sync/run) or by the CLI below.
        votes_proposals_limit     - POST /sync/run ?limit= (1-50, default 10) or CLI --limit:
                                    at most this many incomplete proposals get votes per run.
        initial_proposals_per_dao - only used for a DAO with no stored proposals yet.
    One failing DAO, thread or proposal does not stop the others: each step
    records its own failures and the next run retries them.
    """
    logger.info("=== STARTING FULL DATA SYNC ===")
    proposals = sync_proposals(conn, initial_per_dao=initial_proposals_per_dao)
    forum = fetch_forum_threads(conn, limit=FORUM_THREADS_PER_SYNC)
    votes = fetch_all_votes(conn, max_proposals=votes_proposals_limit)
    audit = audit_collection_status(conn)
    logger.info("=== SYNC FINISHED ===")
    return {"proposals": proposals, "forum": forum, "votes": votes, "current_status": audit}


# ── Command line ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="DAO Governance Data Audit & Sync")
    parser.add_argument("--check", action="store_true", help="Print the audit report (default action)")
    parser.add_argument("--sync-all", action="store_true", help="Proposals, forum and votes, then the audit")
    parser.add_argument("--fetch-proposals", action="store_true", help="Refresh unfinished proposals and add newly published ones")
    parser.add_argument("--fetch-votes", "--fetch-all-votes", dest="fetch_votes", action="store_true",
                        help="Fetch every vote for proposals whose votes are missing or partial")
    parser.add_argument("--space", default=None, help="Limit --fetch-votes to one DAO space id")
    parser.add_argument("--fetch-forum", action="store_true", help="Fetch every post of forum threads that are new, incomplete or recent")
    parser.add_argument("--limit", type=int, default=10, help="Max proposals (votes) or threads (forum) to process per run (default: 10)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        if args.sync_all:
            print_audit_report(sync_all(conn, votes_proposals_limit=args.limit)["current_status"])
        elif args.fetch_proposals:
            print(f"Proposals sync complete: {sync_proposals(conn)}")
        elif args.fetch_votes:
            print(f"Votes sync complete: {fetch_all_votes(conn, max_proposals=args.limit, space_id=args.space)}")
        elif args.fetch_forum:
            print(f"Forum sync complete: {fetch_forum_threads(conn, limit=args.limit)}")
        else:
            print_audit_report(audit_collection_status(conn))
    finally:
        conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# From the API: control returns to features/sync/routes.py run_sync(), which sends
#   the result as JSON.
# From the command line: the audit report is printed and the program ends.
# Recommended next commands after a sync: python -m features.identity.runner --upgrade,
#   then python -m vector.embedding (new posts become searchable in /chat).
