# features/proposals/fetch.py
"""
Keep proposals in step with Snapshot.

Two jobs, both needed every sync:
  1. refresh_unfinished_proposals - every stored proposal that is not over yet
     (still active/pending, or its scores are not final) is re-read BY ID, so
     it keeps updating even after newer proposals push it down the list.
  2. fetch_new_proposals - everything published after the newest proposal we
     have, page by page. A DAO we have never synced starts with its latest
     `initial_per_dao` proposals.

A proposal row is only rewritten when one of its fields actually changed, so
the counts returned are real changes.
"""

import datetime
import json
import logging

from clients.snapshot import get_proposals, get_proposals_by_ids, iter_proposals_created_after
from config.curated_daos import CURATED_DAOS

logger = logging.getLogger(__name__)

# Every field Snapshot can still change after a proposal is first published.
_UPSERT_PROPOSAL_SQL = """
    INSERT INTO proposals
        (id, space_id, title, body, choices_json, state, votes_count, scores_json, scores_total,
         scores_state, created_ts, start_ts, end_ts, link, discussion_url, author, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        title = excluded.title,             body = excluded.body,
        choices_json = excluded.choices_json, state = excluded.state,
        votes_count = excluded.votes_count, scores_json = excluded.scores_json,
        scores_total = excluded.scores_total, scores_state = excluded.scores_state,
        created_ts = excluded.created_ts,   start_ts = excluded.start_ts,
        end_ts = excluded.end_ts,           link = excluded.link,
        discussion_url = excluded.discussion_url, author = excluded.author,
        fetched_at = excluded.fetched_at
    WHERE proposals.title IS NOT excluded.title OR proposals.body IS NOT excluded.body
       OR proposals.choices_json IS NOT excluded.choices_json OR proposals.state IS NOT excluded.state
       OR proposals.votes_count IS NOT excluded.votes_count OR proposals.scores_json IS NOT excluded.scores_json
       OR proposals.scores_total IS NOT excluded.scores_total OR proposals.scores_state IS NOT excluded.scores_state
       OR proposals.created_ts IS NOT excluded.created_ts OR proposals.start_ts IS NOT excluded.start_ts
       OR proposals.end_ts IS NOT excluded.end_ts OR proposals.link IS NOT excluded.link
       OR proposals.discussion_url IS NOT excluded.discussion_url OR proposals.author IS NOT excluded.author
"""


def _save_proposal(conn, p: dict, now: str) -> bool:
    """Insert or update one Snapshot proposal. Returns True if the row is new or changed."""
    cur = conn.execute(_UPSERT_PROPOSAL_SQL, (
        p["id"], p["space"]["id"], p["title"], p["body"], json.dumps(p["choices"]), p["state"],
        p["votes"], json.dumps(p["scores"]), p["scores_total"], p.get("scores_state"),
        p.get("created"), p["start"], p["end"], p.get("link"), p.get("discussion") or None,
        p["author"], now,
    ))
    return cur.rowcount > 0


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def refresh_unfinished_proposals(conn) -> dict:
    """Re-read every stored proposal that is not closed with final scores, by id."""
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM proposals "
        "WHERE state IS NOT 'closed' OR scores_state IS NOT 'final' OR created_ts IS NULL"
    )]
    now = _now()
    live = get_proposals_by_ids(ids) if ids else []
    changed = sum(_save_proposal(conn, p, now) for p in live)
    conn.commit()
    missing = sorted(set(ids) - {p["id"] for p in live})
    if missing:
        logger.warning(f"{len(missing)} stored proposals no longer exist on Snapshot: {missing[:3]}")
    logger.info(f"Refreshed {len(live)} unfinished proposals, {changed} changed")
    return {"checked": len(ids), "changed": changed, "not_on_snapshot": missing}


def fetch_new_proposals(conn, initial_per_dao: int = 20) -> dict:
    """Store every proposal published after the newest one we have, for each curated DAO."""
    now = _now()
    added, failed = 0, []
    for dao in CURATED_DAOS:
        newest = conn.execute(
            "SELECT MAX(created_ts) FROM proposals WHERE space_id = ?", (dao["id"],)
        ).fetchone()[0]
        try:
            if newest is None:
                # Never synced: start from the latest `initial_per_dao` proposals.
                new = get_proposals(dao["id"], first=initial_per_dao)
            else:
                new = list(iter_proposals_created_after(dao["id"], newest))
            added += sum(_save_proposal(conn, p, now) for p in new)
            conn.commit()
            logger.info(f"  [{dao['name']}] {len(new)} new proposals")
        except Exception as e:
            failed.append(dao["id"])
            logger.error(f"  [{dao['name']}] Failed to fetch new proposals: {e}")
    return {"added": added, "failed": failed}


def sync_proposals(conn, initial_per_dao: int = 20) -> dict:
    """Refresh unfinished proposals first (this also fills created_ts), then add new ones."""
    return {"refreshed": refresh_unfinished_proposals(conn),
            "new": fetch_new_proposals(conn, initial_per_dao)}
