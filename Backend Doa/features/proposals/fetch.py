# features/proposals/fetch.py
"""
features/proposals/fetch.py — Keeps the `spaces` and `proposals` tables in step with Snapshot.

WHAT THIS FILE DOES
    sync_proposals() runs three jobs, in this order, every sync:
      1. refresh_spaces               each curated DAO's own row (name, about,
                                      network, Snapshot's total counts)
      2. refresh_unfinished_proposals every stored proposal that is not over yet
                                      (still active/pending, or its scores not final)
                                      is re-read BY ID, so it keeps updating even
                                      after newer proposals push it down the list
      3. fetch_new_proposals          everything published after the newest
                                      proposal we have, page by page; a DAO never
                                      synced starts with its latest `initial_per_dao`
    A proposal row is rewritten only when one of its fields actually changed, so
    the counts returned are real changes, not "rows touched".

WHERE IT SITS
    features/sync/runner.py sync_all()  (POST /sync/run, --sync-all, --fetch-proposals)
        --> THIS FILE --> clients/snapshot.py (network)  and  SQLite (writes)
    After it: features/forum/fetch.py and features/votes/fetch.py use the
    proposals stored here (their discussion links and vote counts).

INPUTS
    conn            - SQLite connection opened by sync_all() or the CLI in
                      features/sync/runner.py (passed down unchanged).
    initial_per_dao - how many proposals to take from a DAO that has never been
                      synced; sync_all passes initial_proposals_per_dao (default 20).
    The DAO list itself comes from config/curated_daos.py.
"""

import datetime
import json
import logging

from clients.snapshot import get_proposals, get_proposals_by_ids, get_space, iter_proposals_created_after
from config.curated_daos import CURATED_DAOS

logger = logging.getLogger(__name__)

# Every field Snapshot can still change after a proposal is first published.
# The WHERE on the update skips rows where nothing differs, so rowcount = real changes.
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

_UPSERT_SPACE_SQL = """
    INSERT INTO spaces (id, name, about, network, proposals_count, followers_count, votes_count, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        name = excluded.name, about = excluded.about, network = excluded.network,
        proposals_count = excluded.proposals_count, followers_count = excluded.followers_count,
        votes_count = excluded.votes_count, fetched_at = excluded.fetched_at
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _save_proposal(conn, p: dict, now: str) -> bool:
    """
    Insert or update one proposal. Returns True if the row is new or changed.

    Parameters (where they come from):
        conn - passed down from sync_proposals().
        p    - one proposal dict exactly as clients/snapshot.py returns it.
        now  - the timestamp of this sync run (stored in fetched_at).
    """
    cur = conn.execute(_UPSERT_PROPOSAL_SQL, (
        p["id"], p["space"]["id"], p["title"], p["body"], json.dumps(p["choices"]), p["state"],
        p["votes"], json.dumps(p["scores"]), p["scores_total"], p.get("scores_state"),
        p.get("created"), p["start"], p["end"], p.get("link"), p.get("discussion") or None,
        p["author"], now,
    ))
    return cur.rowcount > 0


def refresh_spaces(conn) -> dict:
    """
    Store each curated DAO's own info (the rows GET /daos reads).

    Parameter (where it comes from):
        conn - passed down from sync_proposals().
    Returns {"refreshed": n, "failed": [space ids]}. A failure is logged and the
    DAO keeps its previous row.
    """
    now, refreshed, failed = _now(), 0, []
    for dao in CURATED_DAOS:
        try:
            s = get_space(dao["id"])
            if s is None:
                raise ValueError("space not found on Snapshot")
            conn.execute(_UPSERT_SPACE_SQL, (s["id"], s["name"], s["about"], s["network"],
                                             s["proposalsCount"], s["followersCount"], s["votesCount"], now))
            refreshed += 1
        except Exception as e:
            failed.append(dao["id"])
            logger.error(f"  [{dao['name']}] Failed to refresh space: {e}")
    conn.commit()
    return {"refreshed": refreshed, "failed": failed}


def refresh_unfinished_proposals(conn) -> dict:
    """
    Re-read, by id, every stored proposal that is not closed with final scores
    (also rows from older syncs that have no created_ts yet).

    Parameter (where it comes from):
        conn - passed down from sync_proposals().
    Returns {"checked": n, "changed": n, "not_on_snapshot": [ids Snapshot no longer has]}.
    """
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
    """
    For each curated DAO, store every proposal published after the newest one
    we have. A DAO with no stored proposals starts with its latest `initial_per_dao`.

    Parameters (where they come from):
        conn            - passed down from sync_proposals().
        initial_per_dao - passed down from sync_proposals() (default 20).
    Returns {"added": n, "failed": [space ids]}.
    """
    now = _now()
    added, failed = 0, []
    for dao in CURATED_DAOS:
        newest = conn.execute(
            "SELECT MAX(created_ts) FROM proposals WHERE space_id = ?", (dao["id"],)
        ).fetchone()[0]
        try:
            if newest is None:
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
    """
    The three jobs above, in order. Unfinished proposals are refreshed BEFORE
    looking for new ones, because the refresh fills created_ts on old rows and
    "new" means "created after our newest created_ts".

    Parameters (where they come from — features/sync/runner.py):
        conn            - opened by sync_all() or the --fetch-proposals CLI branch.
        initial_per_dao - sync_all's initial_proposals_per_dao (default 20).
    """
    return {"spaces": refresh_spaces(conn),
            "refreshed": refresh_unfinished_proposals(conn),
            "new": fetch_new_proposals(conn, initial_per_dao)}


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/sync/runner.py — sync_all() continues with the forum
#   (features/forum/fetch.py), then the votes (features/votes/fetch.py), which
#   compares each proposal's votes_count stored here with the votes it has.
# If Snapshot fails for one DAO: that DAO is listed in "failed" and the others
#   continue; the next sync retries it.
# If run on its own: python -m features.sync.runner --fetch-proposals
