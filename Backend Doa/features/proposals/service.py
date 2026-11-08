# features/proposals/service.py
"""
features/proposals/service.py — Proposal queries for the proposal endpoints.

WHAT THIS FILE DOES
    Reads proposals from SQLite for features/proposals/routes.py:
      * list_proposals  filtered, most-voted-first list (with forum poster counts)
      * get_proposal    one proposal plus how many of its votes we store
      * concentration   the whale report: largest wallets and their share
    The numbers themselves (silence ratio, winning share, top-voter share,
    choice names) come from features/metrics.py.

WHERE IT SITS
    HTTP request -> features/proposals/routes.py -> THIS FILE -> features/metrics.py
                                                     (SQLite reads only)

INPUTS
    conn - an open SQLite connection; the route handler opens it with
           db.schema.get_connection() and closes it afterwards.
    Everything else comes from the request: URL path (proposal_id) or the query
    string (space_id, state, limit, skip, top_n), validated by FastAPI first.
"""

from features.metrics import FORUM_POSTERS_SQL, top_voter_share


def list_proposals(conn, space_id: str | None, state: str | None, limit: int, skip: int):
    """
    Proposal rows with their forum poster count, most-voted first.

    Parameters (where they come from — all from GET /proposals query string):
        conn     - opened by features/proposals/routes.py list_proposals.
        space_id - ?space_id= (optional) to keep one DAO.
        state    - ?state= (optional): active | closed | pending.
        limit    - ?limit= page size (1-100, default 20).
        skip     - ?skip= how many to skip, for paging.
    Returns sqlite3.Row objects; the route turns them into ProposalSummary.
    """
    clauses, params = [], []
    if space_id:
        clauses.append("p.space_id = ?")
        params.append(space_id)
    if state:
        clauses.append("p.state = ?")
        params.append(state)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    return conn.execute(f"""
        SELECT p.id, p.space_id, p.title, p.state, p.votes_count,
               p.scores_json, p.scores_total, p.link, p.discussion_url,
               p.author, p.start_ts, p.end_ts,
               {FORUM_POSTERS_SQL} AS forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        {where_sql}
        GROUP BY p.id
        ORDER BY p.votes_count DESC
        LIMIT ? OFFSET ?
    """, params + [limit, skip]).fetchall()


def get_proposal(conn, proposal_id: str):
    """
    One proposal row (all columns + forum_posters) and its stored vote count,
    as (row, votes_ingested), or None if it does not exist.

    Parameters (where they come from):
        conn        - opened by features/proposals/routes.py get_proposal.
        proposal_id - the URL path of GET /proposals/{proposal_id}.
    """
    row = conn.execute(f"""
        SELECT p.*, {FORUM_POSTERS_SQL} AS forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.id = ?
        GROUP BY p.id
    """, (proposal_id,)).fetchone()
    if not row:
        return None
    votes_ingested = conn.execute(
        "SELECT COUNT(*) FROM votes WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()[0]
    return row, votes_ingested


def concentration(conn, proposal_id: str, top_n: int):
    """
    The whale report for GET /proposals/{id}/concentration.

    Parameters (where they come from):
        conn        - opened by features/proposals/routes.py get_concentration.
        proposal_id - the URL path.
        top_n       - ?top_n= (1-50, default 4).

    Returns None if the proposal does not exist; otherwise the fields of
    ConcentrationReport (total_voters_ingested == 0 means no votes are stored).
    The share itself is metrics.top_voter_share, the same number the chat uses.
    """
    report = top_voter_share(conn, proposal_id, top_n)
    if report is None:
        return None
    if report["stored_votes"] == 0:
        return {"title": report["title"], "total_voters_ingested": 0}

    if report["partial"]:
        note = (f"Partial data: {report['stored_votes']} of {report['expected_votes']} votes are "
                "stored; shares are measured against Snapshot's full tally.")
    else:
        note = f"Complete data: all {report['stored_votes']} votes are stored."

    return {
        "title": report["title"],
        "total_voters_ingested": report["stored_votes"],
        "total_voting_power": report["total_voting_power"],
        "top_n_power": report["top_n_power"],
        "top_n_share_pct": report["top_n_share_pct"],
        "top_voters": report["top_voters"],
        "note": note,
    }


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/proposals/routes.py, which adds the per-row
# numbers (metrics.silence_ratio_pct / winning_share_pct) and builds the
# response models sent to the client.
# If the proposal does not exist: get_proposal / concentration return None and
#   the route answers 404.
# If its votes are not stored yet: concentration returns total_voters_ingested=0
#   and the route answers 404 with "run the vote ingestion first"
#   (python -m features.sync.runner --fetch-votes).
