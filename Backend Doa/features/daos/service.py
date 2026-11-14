# features/daos/service.py
"""
features/daos/service.py — DAO-level numbers, read from SQLite.

WHAT THIS FILE DOES
    Answers "how does this DAO govern?" for the DAO endpoints:
      * get_space          the DAO's own row (name, network, about)
      * compute_dao_stats  forum coverage, average silence ratio and average
                           winning-choice share across the DAO's proposals
      * top_proposals      the DAO's most-voted proposals, each with its numbers
    Every formula comes from features/metrics.py, so these numbers always agree
    with the proposal endpoints and the chat.

WHERE IT SITS
    HTTP request -> features/daos/routes.py -> THIS FILE -> features/metrics.py
                                               (SQLite reads only, no writes)

INPUTS
    conn     - an open SQLite connection; the route handler opens it with
               db.schema.get_connection() and closes it afterwards.
    space_id - a Snapshot space id such as "ens.eth"; GET /daos loops over
               config/curated_daos.py, GET /daos/{space_id} takes it from the URL.
"""

from features.metrics import FORUM_POSTERS_SQL, proposal_status, silence_ratio_pct, winning_share_pct


def get_space(conn, space_id: str):
    """
    The `spaces` row for one DAO (id, name, about, network, ...), or None.

    Parameters (where they come from):
        conn     - opened by features/daos/routes.py (list_daos / get_dao).
        space_id - from CURATED_DAOS (list_daos) or the URL path (get_dao).
    """
    return conn.execute("SELECT * FROM spaces WHERE id = ?", (space_id,)).fetchone()


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_dao_stats(conn, space_id: str) -> dict:
    """
    Aggregated numbers for one DAO.

    Parameters (where they come from):
        conn     - opened by features/daos/routes.py.
        space_id - see get_space.

    Returns:
        proposals_ingested       proposals we store for this DAO
        proposals_with_forum     how many of them have at least one forum post
        forum_coverage_pct       the two above as a %
        avg_silence_ratio_pct    mean of each proposal's posters ÷ voters (%)
        avg_top_choice_share_pct mean of each proposal's winning-choice share (%)
    Averages are taken over unrounded values and rounded once at the end.
    """
    proposals = conn.execute(f"""
        SELECT p.votes_count, p.scores_json, p.scores_total,
               {FORUM_POSTERS_SQL} AS forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.space_id = ?
        GROUP BY p.id
    """, (space_id,)).fetchall()

    total = len(proposals)
    with_forum = sum(1 for p in proposals if p["forum_posters"] > 0)
    silence = [s for p in proposals
               if (s := silence_ratio_pct(p["forum_posters"], p["votes_count"], decimals=None)) is not None]
    winning = [w for p in proposals
               if (w := winning_share_pct(p["scores_json"], p["scores_total"], decimals=None)) is not None]

    return {
        "proposals_ingested": total,
        "proposals_with_forum": with_forum,
        "forum_coverage_pct": round(100 * with_forum / total, 1) if total else 0.0,
        "avg_silence_ratio_pct": round(_average(silence), 3),
        "avg_top_choice_share_pct": round(_average(winning), 1),
    }


def top_proposals(conn, space_id: str, limit: int = 5) -> list[dict]:
    """
    The DAO's most-voted proposals, each with its silence ratio and winning share.

    Parameters (where they come from):
        conn     - opened by features/daos/routes.py get_dao.
        space_id - from the URL path of GET /daos/{space_id}.
        limit    - how many to return; get_dao uses the default 5.
    """
    rows = conn.execute(f"""
        SELECT p.id, p.title, p.state, p.votes_count, p.scores_json, p.scores_total, p.link,
               p.start_ts, p.end_ts, p.scores_state, p.fetched_at,
               {FORUM_POSTERS_SQL} AS forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.space_id = ?
        GROUP BY p.id
        ORDER BY p.votes_count DESC
        LIMIT ?
    """, (space_id, limit)).fetchall()

    return [
        {
            "id": p["id"],
            "title": p["title"],
            "state": p["state"],
            "status": proposal_status(p)["status"],
            "votes_count": p["votes_count"] or 0,
            "forum_posters": p["forum_posters"] or 0,
            "silence_ratio_pct": silence_ratio_pct(p["forum_posters"], p["votes_count"]),
            "top_choice_share_pct": winning_share_pct(p["scores_json"], p["scores_total"]),
            "link": p["link"],
        }
        for p in rows
    ]


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/daos/routes.py, which wraps these dicts in the
# DAOSummary / DAODetail response models and sends them to the client.
# If the DAO has no proposals yet: compute_dao_stats returns zeros and
#   top_proposals an empty list (no error).
# Related next read: features/proposals/service.py (the same numbers per proposal).
