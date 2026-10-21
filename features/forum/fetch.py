# features/forum/fetch.py
"""
Download Discourse threads until every linked thread is complete, and keep
recent threads up to date (discussion often continues after the vote).

How it works, step by step:
  1. Ask `forum_completeness` for every thread linked from a proposal.
  2. Pick the ones to fetch: not fetched yet, failed last time, partial, or
     recently active and not checked for `refresh_days`.
  3. Fetch the first page plus only the posts we do not have yet.
  4. Save each post once per proposal that links the thread, and record what
     Discourse listed in `forum_threads`.
"""

import datetime
import logging

from clients.discourse import fetch_full_thread, post_record
from features.forum.completeness import COMPLETE, forum_completeness

logger = logging.getLogger(__name__)

_UPSERT_POST_SQL = """
    INSERT INTO forum_posts (id, proposal_id, topic_id, post_number, username, content, created_at, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(proposal_id, id) DO UPDATE SET
        content    = excluded.content,       -- posts can be edited
        fetched_at = excluded.fetched_at
"""


def _days_ago(days: float) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)


def needs_fetch(thread: dict, refresh_days: float, recent_days: float) -> bool:
    """Fetch anything not complete; re-check complete threads only while they are recent."""
    if thread["status"] != COMPLETE:
        return True
    recent = thread["active"] or thread["newest_end_ts"] >= _days_ago(recent_days).timestamp()
    stale = datetime.datetime.fromisoformat(thread["last_fetched_at"]) < _days_ago(refresh_days)
    return recent and stale


def _known_ids(conn, proposal_ids: list[str]) -> set[int]:
    """Post ids already stored for EVERY proposal linking the thread (so none is skipped wrongly)."""
    sets = [{r[0] for r in conn.execute("SELECT id FROM forum_posts WHERE proposal_id = ?", (pid,))}
            for pid in proposal_ids]
    return set.intersection(*sets) if sets else set()


def _record_thread(conn, url, topic_id=None, listed=None, unavailable=None, error=None):
    """Save the outcome of one fetch attempt. A failure keeps the last good numbers."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if error:
        conn.execute(
            "INSERT INTO forum_threads (url, last_error) VALUES (?, ?) "
            "ON CONFLICT(url) DO UPDATE SET last_error = excluded.last_error",
            (url, error[:500]),
        )
    else:
        conn.execute(
            """INSERT INTO forum_threads (url, topic_id, listed_posts, unavailable, last_fetched_at, last_error)
               VALUES (?, ?, ?, ?, ?, NULL)
               ON CONFLICT(url) DO UPDATE SET
                   topic_id = excluded.topic_id, listed_posts = excluded.listed_posts,
                   unavailable = excluded.unavailable, last_fetched_at = excluded.last_fetched_at,
                   last_error = NULL""",
            (url, topic_id, listed, unavailable, now),
        )
    conn.commit()


def fetch_forum_threads(conn, limit: int = 20, refresh_days: float = 1, recent_days: float = 30) -> dict:
    """
    Fetch up to `limit` threads that need it (see `needs_fetch`).
    Returns {"threads_processed": n, "posts_written": n, "failed": [urls]}.
    """
    todo = [t for t in forum_completeness(conn) if needs_fetch(t, refresh_days, recent_days)][:limit]
    logger.info(f"Fetching {len(todo)} forum threads...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    processed, written, failed = 0, 0, []

    for t in todo:
        try:
            known = _known_ids(conn, t["proposal_ids"])
            thread = fetch_full_thread(t["url"], known_ids=known)
            posts = [post_record(raw, thread["topic_id"]) for raw in thread["posts"]]

            rows = [(p["id"], pid, p["topic_id"], p["post_number"], p["username"],
                     p["content"], p["created_at"], now)
                    for pid in t["proposal_ids"] for p in posts]
            conn.executemany(_UPSERT_POST_SQL, rows)

            received = known | {p["id"] for p in posts}
            unavailable = len(set(thread["listed_ids"]) - received)
            _record_thread(conn, t["url"], thread["topic_id"], len(thread["listed_ids"]), unavailable)

            processed += 1
            written += len(rows)
            logger.info(f"  + {len(posts)} posts ({len(thread['listed_ids'])} listed, "
                        f"{unavailable} unavailable) for {len(t['proposal_ids'])} proposal(s): {t['url']}")
        except Exception as e:
            conn.rollback()
            _record_thread(conn, t["url"], error=f"{type(e).__name__}: {e}")
            failed.append(t["url"])
            logger.warning(f"  Failed {t['url']}: {e}")

    return {"threads_processed": processed, "posts_written": written, "failed": failed}
