# features/forum/completeness.py
"""
One rule, used everywhere: is a forum thread's data complete?

Every proposal can link one Discourse thread (`proposals.discussion_url`).
When we fetch a thread we record in `forum_threads` how many posts Discourse
listed and how many of those it would not return (deleted or hidden). A
thread is then:

    not_fetched - we have never fetched it
    error       - the last attempt failed (it is retried next time)
    partial     - some listed posts are missing for at least one linked proposal
    complete    - every available post is stored for every linked proposal

Several proposals can link the same thread, so the status is per THREAD and
lists every proposal that links it.
"""

from clients.discourse import normalize_discourse_url

NOT_FETCHED, ERROR, PARTIAL, COMPLETE = "not_fetched", "error", "partial", "complete"


def linked_threads(conn) -> dict[str, list]:
    """{thread url: [proposal rows linking it]}. Only Discourse topic links (/t/) count."""
    threads: dict[str, list] = {}
    for p in conn.execute(
        "SELECT id, state, end_ts, discussion_url FROM proposals "
        "WHERE discussion_url LIKE '%/t/%' AND discussion_url NOT LIKE '%gist.github%'"
    ):
        threads.setdefault(normalize_discourse_url(p["discussion_url"]), []).append(p)
    return threads


def thread_status(fetched: bool, error: str | None, listed: int, unavailable: int, stored: int) -> str:
    """Status for one thread. `stored` is the post count of its least-complete proposal."""
    if not fetched:
        return ERROR if error else NOT_FETCHED
    if error:
        return ERROR
    return COMPLETE if stored + unavailable >= listed else PARTIAL


def forum_completeness(conn) -> list[dict]:
    """One row per linked thread, with what Discourse listed, what we stored, and the status."""
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
