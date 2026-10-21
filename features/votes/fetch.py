# features/votes/fetch.py
"""Pull votes from Snapshot: a quick capped fetch and a complete cursor-paged fetch."""

import datetime
import json
import logging
import time
from typing import Dict

from clients.snapshot import get_votes, iter_all_votes

logger = logging.getLogger(__name__)


def fetch_missing_votes(conn, max_proposals: int = 10, votes_per_prop: int = 500) -> Dict[str, int]:
    """
    Fetches votes for proposals in SQLite that currently have 0 votes recorded.
    """
    targets = conn.execute("""
        SELECT p.id, p.title, p.space_id, p.votes_count
        FROM proposals p
        LEFT JOIN votes v ON p.id = v.proposal_id
        WHERE v.proposal_id IS NULL AND p.votes_count > 0
        ORDER BY p.votes_count DESC
        LIMIT ?
    """, (max_proposals,)).fetchall()

    logger.info(f"Ingesting votes for {len(targets)} proposals with missing vote records...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total_votes_ingested = 0
    props_done = 0

    for p in targets:
        try:
            votes = get_votes(p["id"], first=votes_per_prop, skip=0)
            for v in votes:
                vote_key = f"{p['id']}_{v['voter']}"
                conn.execute("""
                    INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vote_key) DO UPDATE SET
                        choice_json = excluded.choice_json,
                        vp = excluded.vp,
                        fetched_at = excluded.fetched_at
                """, (
                    vote_key, p["id"], v["voter"], json.dumps(v["choice"]),
                    v["vp"], v["created"], now
                ))
            conn.commit()
            props_done += 1
            total_votes_ingested += len(votes)
            logger.info(f"  + {len(votes)} votes for [{p['space_id']}] '{p['title'][:40]}'")
            time.sleep(0.2)  # Avoid Snapshot rate limiting
        except Exception as e:
            logger.error(f"  Failed votes for {p['id']}: {e}")

    return {"proposals_completed": props_done, "votes_ingested": total_votes_ingested}


def fetch_all_votes(conn, max_proposals: int = 10, space_id: str | None = None,
                    batch_size: int = 1000) -> Dict[str, int]:
    """
    Fetches EVERY vote for proposals whose stored votes are incomplete
    (stored < Snapshot's votes_count), using cursor paging so there is no
    6000-vote ceiling. Safe to re-run: it resumes from the last stored vote
    timestamp, and proposals that are already complete are skipped.
    """
    targets = conn.execute("""
        SELECT p.id, p.title, p.space_id, p.votes_count, COUNT(v.vote_key) AS stored,
               IFNULL(MAX(v.created_ts), 0) AS last_ts
        FROM proposals p
        LEFT JOIN votes v ON v.proposal_id = p.id
        WHERE p.votes_count > 0 AND (? IS NULL OR p.space_id = ?)
        GROUP BY p.id
        HAVING stored < p.votes_count * 0.999
        ORDER BY p.votes_count ASC
        LIMIT ?
    """, (space_id, space_id, max_proposals)).fetchall()

    logger.info(f"Fetching ALL votes for {len(targets)} incomplete proposals...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total, done = 0, 0

    for p in targets:
        try:
            n, batch = 0, []
            for v in iter_all_votes(p["id"], start_ts=p["last_ts"]):
                batch.append((f"{p['id']}_{v['voter']}", p["id"], v["voter"],
                              json.dumps(v["choice"]), v["vp"], v["created"], now))
                if len(batch) >= batch_size:
                    conn.executemany("""
                        INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(vote_key) DO UPDATE SET
                            choice_json = excluded.choice_json, vp = excluded.vp,
                            fetched_at = excluded.fetched_at
                    """, batch)
                    conn.commit()
                    n += len(batch)
                    batch = []
            if batch:
                conn.executemany("""
                    INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vote_key) DO UPDATE SET
                        choice_json = excluded.choice_json, vp = excluded.vp,
                        fetched_at = excluded.fetched_at
                """, batch)
                conn.commit()
                n += len(batch)
            total += n
            done += 1
            logger.info(f"  + {n}/{p['votes_count']} votes for [{p['space_id']}] '{p['title'][:40]}'")
        except Exception as e:
            logger.error(f"  Failed votes for {p['id']}: {e}")

    return {"proposals_completed": done, "votes_ingested": total}
