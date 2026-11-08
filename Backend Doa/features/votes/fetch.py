# features/votes/fetch.py
"""
features/votes/fetch.py — Downloads votes until every proposal's vote data is complete.

How it works, step by step:
  1. Ask `vote_completeness` which proposals are `missing` or `partial`.
  2. For each one, page through Snapshot's votes, starting from the newest
     vote we already have (so a re-run only downloads what is new).
  3. Save votes in batches. Each vote has a fixed key (proposal + voter), so
     saving the same vote twice updates it instead of creating a duplicate.

WHERE IT SITS
    features/sync/runner.py sync_all()  (POST /sync/run, --sync-all, --fetch-votes)
        --> THIS FILE --> clients/snapshot.py iter_all_votes (network) and SQLite (writes)
    It runs after the proposal sync, because it compares each proposal's
    votes_count (refreshed there) with the votes stored here.
"""

import datetime
import json
import logging

from clients.snapshot import iter_all_votes
from features.votes.completeness import MISSING, PARTIAL, vote_completeness

logger = logging.getLogger(__name__)

SAVE_BATCH_SIZE = 1000   # votes written per database transaction

_UPSERT_VOTE_SQL = """
    INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(vote_key) DO UPDATE SET
        choice_json = excluded.choice_json,
        vp          = excluded.vp,
        fetched_at  = excluded.fetched_at
"""


def _save_votes(conn, rows: list[tuple]) -> int:
    """
    Write one batch of vote rows and commit. Returns how many were written.

    Parameters (where they come from — fetch_all_votes below):
        conn - passed down.
        rows - up to SAVE_BATCH_SIZE tuples in _UPSERT_VOTE_SQL column order.
    Committing per batch means an interrupted run keeps what it already saved.
    """
    if rows:
        conn.executemany(_UPSERT_VOTE_SQL, rows)
        conn.commit()
    return len(rows)


def fetch_all_votes(conn, max_proposals: int = 10, space_id: str | None = None) -> dict:
    """
    Fetch every vote for up to `max_proposals` proposals whose votes are
    missing or partial (smallest first, so many proposals finish quickly).
    Pass `space_id` to work on one DAO only.

    Returns {"proposals_processed": n, "votes_ingested": n, "failed": [ids]}.
    "Processed" means the download finished without an error; the audit
    (vote_completeness) is what says whether the data is now complete.

    Parameters (where they come from — features/sync/runner.py):
        conn          - opened by sync_all() or the --fetch-votes CLI branch.
        max_proposals - sync_all's votes_proposals_limit (POST /sync/run ?limit=,
                        default 10) or the CLI --limit (use 200 for a backfill).
        space_id      - the CLI --space flag (one DAO), else None.
    """
    todo = [r for r in vote_completeness(conn, space_id) if r["status"] in (MISSING, PARTIAL)]
    todo.sort(key=lambda r: r["expected"])
    todo = todo[:max_proposals]

    logger.info(f"Fetching votes for {len(todo)} incomplete proposals...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total, processed, failed = 0, 0, []

    for p in todo:
        try:
            saved, batch = 0, []
            for v in iter_all_votes(p["proposal_id"], start_ts=p["last_vote_ts"]):
                batch.append((
                    f"{p['proposal_id']}_{v['voter']}",   # vote_key: one vote per voter per proposal
                    p["proposal_id"], v["voter"], json.dumps(v["choice"]),
                    v["vp"], v["created"], now,
                ))
                if len(batch) >= SAVE_BATCH_SIZE:
                    saved += _save_votes(conn, batch)
                    batch = []
            saved += _save_votes(conn, batch)

            total += saved
            processed += 1
            logger.info(f"  + {saved} votes for [{p['space_id']}] '{p['title'][:40]}' "
                        f"(had {p['stored']}/{p['expected']})")
        except Exception as e:
            failed.append(p["proposal_id"])
            logger.error(f"  Failed votes for {p['proposal_id']}: {e}")

    return {"proposals_processed": processed, "votes_ingested": total, "failed": failed}


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/sync/runner.py — sync_all() finishes with the audit
#   (features/sync/audit.py), whose vote "completeness" section reports the result.
# Votes feed: features/metrics.py (whale shares) and features/chat/context.py
#   (what a forum author voted), and identity upgrades (features/identity/runner.py --upgrade).
# If one proposal fails: its id is in "failed", the others continue, and the next
#   run resumes it from its newest stored vote.
