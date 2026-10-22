# features/forum/completeness.py
"""
features/forum/completeness.py — One rule for "is a forum thread's data complete?".

WHAT THIS FILE DOES
    Every proposal can link one Discourse thread (proposals.discussion_url).
    When features/forum/fetch.py fetches a thread it records in `forum_threads`
    how many posts Discourse listed and how many of those it would not return
    (deleted or hidden). Comparing that with what we stored gives a status:

        not_fetched - we have never fetched it
        error       - the last attempt failed (it is retried next time)
        partial     - some listed posts are missing for at least one linked proposal
        complete    - every available post is stored for every linked proposal

    Several proposals can link the same thread, so the status is per THREAD
    and lists every proposal that links it. Both the fetcher (what to download)
    and the audit (what to report) use this file, so they can never disagree.

WHERE IT SITS
    features/forum/fetch.py  ──┐
    features/sync/audit.py   ──┴─> THIS FILE ─> SQLite (read-only)

INPUTS
    conn - an open SQLite connection, passed in by the caller above.
"""

from clients.discourse import is_discourse_thread, normalize_discourse_url

NOT_FETCHED, ERROR, PARTIAL, COMPLETE = "not_fetched", "error", "partial", "complete"


def linked_threads(conn) -> dict[str, list]:
    """
    {thread url: [proposal rows linking it]}. Only Discourse topic links count
    (see clients/discourse.py is_discourse_thread); URLs are normalized, so two
    different links to the same thread end up under one key.

    Parameter (where it comes from):
        conn - passed in by forum_completeness().
    """
    threads: dict[str, list] = {}
    for p in conn.execute("SELECT id, state, end_ts, discussion_url FROM proposals"):
        if is_discourse_thread(p["discussion_url"]):
            threads.setdefault(normalize_discourse_url(p["discussion_url"]), []).append(p)
    return threads


def thread_status(fetched: bool, error: str | None, listed: int, unavailable: int, stored: int) -> str:
    """
    The status of one thread (see the table at the top).

    Parameters (where they come from — forum_completeness below):
        fetched     - forum_threads.last_fetched_at is set.
        error       - forum_threads.last_error (None when the last attempt worked).
        listed      - forum_threads.listed_posts: ids Discourse listed.
        unavailable - forum_threads.unavailable: listed ids it did not return.
        stored      - posts stored for the least-complete linked proposal.
    """
    if not fetched:
        return ERROR if error else NOT_FETCHED
    if error:
        return ERROR
    return COMPLETE if stored + unavailable >= listed else PARTIAL


def forum_completeness(conn) -> list[dict]:
    """
    One row per linked thread: url, proposal_ids, stored, listed, unavailable,
    last_fetched_at, last_error, active (any linked proposal still open),
    newest_end_ts, status.

    Parameter (where it comes from):
        conn - opened by fetch_forum_threads()'s caller (features/sync/runner.py)
               or by audit_collection_status()'s caller (sync routes / runner).
    """
    recorded = {r["url"]: r for r in conn.execute("SELECT * FROM forum_threads")}
    rows = []
    for url, proposals in linked_threads(conn).items():
        ids = [p["id"] for p in proposals]
        stored = min(
            conn.execute("SELECT COUNT(*) FROM forum_posts WHERE proposal_id = ?", (pid,)).fetchone()[0]
            for pid in ids
        )
        t = recorded.get(url)
        fetched = bool(t and t["last_fetched_at"])
        listed = (t["listed_posts"] or 0) if t else 0
        unavailable = (t["unavailable"] or 0) if t else 0
        error = t["last_error"] if t else None
        rows.append({
            "url": url,
            "proposal_ids": ids,
            "stored": stored,
            "listed": listed,
            "unavailable": unavailable,
            "last_fetched_at": t["last_fetched_at"] if t else None,
            "last_error": error,
            "active": any(p["state"] == "active" for p in proposals),
            "newest_end_ts": max((p["end_ts"] or 0) for p in proposals),
            "status": thread_status(fetched, error, listed, unavailable, stored),
        })
    return rows


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller:
#   features/forum/fetch.py  -> picks the threads that need fetching (needs_fetch)
#   features/sync/audit.py   -> counts statuses for /sync/status and --check
# If a proposal links a non-forum page (e.g. a gist): it is not a thread here,
#   so it is neither fetched nor counted as missing.
