# features/votes/completeness.py
"""
features/votes/completeness.py — One rule for "is a proposal's vote data complete?".

Snapshot tells us how many votes a proposal has (`proposals.votes_count`).
We count how many we have stored. Comparing the two gives a status:

    no_votes  - Snapshot reports 0 votes, so there is nothing to fetch
    missing   - Snapshot has votes, we have stored none
    partial   - we have some, but fewer than Snapshot reports
    complete  - we have all of them

WHO USES IT (so they can never disagree)
    features/votes/fetch.py   which proposals still need votes downloaded
    features/sync/audit.py    the completeness report (/sync/status, --check)
    features/metrics.py       whether a whale share is based on partial data

INPUTS
    conn - an open SQLite connection, passed in by the callers above.
"""

NO_VOTES, MISSING, PARTIAL, COMPLETE = "no_votes", "missing", "partial", "complete"


def vote_status(expected: int | None, stored: int) -> str:
    """
    Status for one proposal.

    Parameters (where they come from):
        expected - proposals.votes_count: Snapshot's own count (features/proposals/fetch.py).
        stored   - how many vote rows we have (vote_completeness, or metrics.top_voter_share).
    "complete" also covers stored > expected: votes can arrive after the
    proposal's count was last refreshed.
    """
    expected = expected or 0
    if expected == 0:
        return NO_VOTES
    if stored == 0:
        return MISSING
    if stored < expected:
        return PARTIAL
    return COMPLETE


def vote_completeness(conn, space_id: str | None = None) -> list[dict]:
    """
    One row per proposal: expected vs stored votes, the newest stored vote's
    timestamp (where a resumed fetch should start), and the status.

    Parameters (where they come from):
        conn     - opened by the caller (sync runner / sync routes).
        space_id - optional DAO filter; fetch_all_votes passes the --space CLI flag.
    """
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.space_id,
               IFNULL(p.votes_count, 0)        AS expected,
               COUNT(v.vote_key)               AS stored,
               IFNULL(MAX(v.created_ts), 0)    AS last_vote_ts
        FROM proposals p
        LEFT JOIN votes v ON v.proposal_id = p.id
        WHERE (? IS NULL OR p.space_id = ?)
        GROUP BY p.id
        """,
        (space_id, space_id),
    ).fetchall()

    return [
        {
            "proposal_id": r["id"],
            "title": r["title"],
            "space_id": r["space_id"],
            "expected": r["expected"],
            "stored": r["stored"],
            "last_vote_ts": r["last_vote_ts"],
            "status": vote_status(r["expected"], r["stored"]),
        }
        for r in rows
    ]


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller:
#   features/votes/fetch.py -> downloads votes for the "missing" / "partial" rows
#   features/sync/audit.py  -> counts the statuses for the audit report
