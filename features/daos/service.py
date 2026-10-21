# features/daos/service.py
"""DAO-level statistics computed from SQLite."""

import json


def get_space(conn, space_id: str):
    return conn.execute("SELECT * FROM spaces WHERE id = ?", (space_id,)).fetchone()


def compute_dao_stats(conn, space_id: str) -> dict:
    """Aggregated stats for one DAO: forum coverage, avg silence ratio, avg winning-choice share."""
    proposals = conn.execute("""
        SELECT p.id, p.votes_count, p.scores_json, p.scores_total,
               COUNT(DISTINCT fp.username) as forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.space_id = ?
        GROUP BY p.id
    """, (space_id,)).fetchall()

    total = len(proposals)
    with_forum = sum(1 for p in proposals if p["forum_posters"] > 0)

    silence_ratios = []
    top_choice_shares = []

    for p in proposals:
        votes = p["votes_count"] or 0
        posters = p["forum_posters"] or 0
        if votes > 0:
            silence_ratios.append(posters / votes)

        scores = json.loads(p["scores_json"]) if p["scores_json"] else []
        score_total = p["scores_total"] or 0
        if score_total > 0 and scores:
            top_choice_shares.append(max(scores) / score_total)

    avg_silence = (sum(silence_ratios) / len(silence_ratios)) if silence_ratios else 0.0
    avg_top_choice = (sum(top_choice_shares) / len(top_choice_shares)) if top_choice_shares else 0.0

    return {
        "proposals_ingested": total,
        "proposals_with_forum": with_forum,
        "forum_coverage_pct": round((with_forum / total * 100) if total else 0, 1),
        "avg_silence_ratio_pct": round(avg_silence * 100, 3),
        "avg_top_choice_share_pct": round(avg_top_choice * 100, 1),
    }


def top_proposals(conn, space_id: str, limit: int = 5) -> list[dict]:
    """Top proposals of a DAO by vote count, each with silence ratio and winning-choice share."""
    rows = conn.execute("""
        SELECT p.id, p.title, p.state, p.votes_count, p.scores_json,
               p.scores_total, p.link, p.start_ts, p.end_ts,
               COUNT(DISTINCT fp.username) as forum_posters
        FROM proposals p
        LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
        WHERE p.space_id = ?
        GROUP BY p.id
        ORDER BY p.votes_count DESC
        LIMIT ?
    """, (space_id, limit)).fetchall()

    result = []
    for p in rows:
        votes = p["votes_count"] or 0
        posters = p["forum_posters"] or 0
        scores = json.loads(p["scores_json"]) if p["scores_json"] else []
        score_total = p["scores_total"] or 0
        top_share = (max(scores) / score_total * 100) if score_total > 0 and scores else None

        result.append({
            "id": p["id"],
            "title": p["title"],
            "state": p["state"],
            "votes_count": votes,
            "forum_posters": posters,
            "silence_ratio_pct": round(posters / votes * 100, 3) if votes > 0 else None,
            "top_choice_share_pct": round(top_share, 1) if top_share is not None else None,
            "link": p["link"],
        })
    return result
