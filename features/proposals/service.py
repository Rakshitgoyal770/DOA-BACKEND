# features/proposals/service.py
"""Proposal queries and governance metrics (silence ratio, winning share, whale concentration)."""

import json


def silence_ratio(votes_count: int | None, forum_posters: int) -> float | None:
    """forum_posters / votes_count as a percentage."""
    if votes_count and votes_count > 0:
        return round(forum_posters / votes_count * 100, 3)
    return None


def top_choice_share(scores_json: str | None, scores_total: float | None) -> float | None:
    """Winning choice's share of total voting weight, as a percentage."""
    if not scores_json or not scores_total or scores_total == 0:
        return None
    try:
        scores = json.loads(scores_json)
        return round(max(scores) / scores_total * 100, 1) if scores else None
    except Exception:
        return None


def decode_choice(choice_json: str, choices: list):
    """Snapshot uses 1-indexed integers for single choice; anything else is returned as stored."""
    try:
        raw = json.loads(choice_json)
        if isinstance(raw, int) and 0 < raw <= len(choices):
            return choices[raw - 1]
        return raw
    except Exception:
        return choice_json


def list_proposals(conn, space_id: str | None, state: str | None, limit: int, skip: int):
    """Proposal rows (with distinct forum poster count), most-voted first."""
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
               COUNT(DISTINCT fp.username) as forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        {where_sql}
        GROUP BY p.id
        ORDER BY p.votes_count DESC
        LIMIT ? OFFSET ?
    """, params + [limit, skip]).fetchall()


def get_proposal(conn, proposal_id: str):
    """One proposal row with forum poster count and stored vote count, or None."""
    row = conn.execute("""
        SELECT p.*, COUNT(DISTINCT fp.username) as forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.id = ?
        GROUP BY p.id
    """, (proposal_id,)).fetchone()
    if not row:
        return None
    votes_ingested = conn.execute(
        "SELECT COUNT(*) as c FROM votes WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()["c"]
    return row, votes_ingested


def concentration(conn, proposal_id: str, top_n: int):
    """
    Voting-power concentration of a proposal's stored votes.
    Returns None if the proposal does not exist, or a dict (total_voters_ingested == 0 if no votes stored).
    """
    p = conn.execute(
        "SELECT title, choices_json, votes_count FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if not p:
        return None

    choices = json.loads(p["choices_json"]) if p["choices_json"] else []
    all_votes = conn.execute("""
        SELECT voter, vp, choice_json
        FROM votes
        WHERE proposal_id = ?
        ORDER BY vp DESC
    """, (proposal_id,)).fetchall()
    if not all_votes:
        return {"title": p["title"], "total_voters_ingested": 0}

    total_vp = sum(v["vp"] for v in all_votes if v["vp"])
    top_votes = all_votes[:top_n]
    top_vp = sum(v["vp"] for v in top_votes if v["vp"])

    stored, expected = len(all_votes), p["votes_count"] or 0
    if expected and stored < expected * 0.999:
        note = (f"Partial data: {stored} of {expected} votes are stored, so shares are measured "
                f"against the stored votes only and may differ from the full tally.")
    else:
        note = f"Complete data: all {stored} votes are stored."

    return {
        "title": p["title"],
        "total_voters_ingested": stored,
        "total_voting_power": round(total_vp, 2),
        "top_n_power": round(top_vp, 2),
        "top_n_share_pct": round(top_vp / total_vp * 100, 1) if total_vp else 0,
        "top_voters": [
            {
                "voter": v["voter"],
                "voting_power": round(v["vp"], 4),
                "power_share_pct": round(v["vp"] / total_vp * 100, 2) if total_vp else 0,
                "choice": decode_choice(v["choice_json"], choices),
            }
            for v in top_votes
        ],
        "note": note,
    }
