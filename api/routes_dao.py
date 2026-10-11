# api/routes_dao.py
"""
GET /daos        — List all curated DAOs with live stats.
GET /daos/{id}   — Single DAO detail with per-proposal silence summary.
"""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.schema import get_connection
from config.curated_daos import CURATED_DAOS

router = APIRouter(prefix="/daos", tags=["DAOs"])


# ── Response schemas ──────────────────────────────────────────────────────────

class DAOSummary(BaseModel):
    id: str
    name: str
    network: str | None
    about: str | None
    proposals_ingested: int
    proposals_with_forum: int
    forum_coverage_pct: float          # % of proposals that have linked forum threads
    avg_silence_ratio_pct: float       # avg forum_posters / votes_count across proposals
    avg_top_choice_share_pct: float    # avg dominance of the winning choice


class DAODetail(DAOSummary):
    space_snapshot_url: str
    top_proposals: list[dict]          # top 5 by vote count with silence ratio


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_dao_stats(space_id: str, conn) -> dict:
    """Computes aggregated stats for one DAO from local DB."""
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DAOSummary], summary="List all curated DAOs")
def list_daos():
    """
    Returns all 5 curated DAOs with aggregated governance stats:
    - Forum coverage (% of proposals with linked discussions)
    - Average silence ratio (forum posters vs. total voters)
    - Average winning-choice dominance (concentration of vote weight)

    These stats surface the core insight: governance is decided by a
    tiny fraction of token holders who never explain themselves publicly.
    """
    conn = get_connection()
    try:
        results = []
        for dao in CURATED_DAOS:
            space_row = conn.execute(
                "SELECT * FROM spaces WHERE id = ?", (dao["id"],)
            ).fetchone()

            stats = _compute_dao_stats(dao["id"], conn)

            results.append(DAOSummary(
                id=dao["id"],
                name=dao["name"],
                network=space_row["network"] if space_row else None,
                about=space_row["about"] if space_row else None,
                **stats,
            ))
        return results
    finally:
        conn.close()


@router.get("/{space_id}", response_model=DAODetail, summary="Single DAO with top proposals")
def get_dao(space_id: str):
    """
    Returns full detail for one DAO including its top 5 proposals by vote count,
    each annotated with silence ratio and winning-choice concentration.

    Use the `space_id` values from GET /daos (e.g. `arbitrumfoundation.eth`).
    """
    # Validate against curated list
    known_ids = {dao["id"] for dao in CURATED_DAOS}
    if space_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"DAO '{space_id}' not in curated list. "
                   f"Valid IDs: {sorted(known_ids)}"
        )

    conn = get_connection()
    try:
        space_row = conn.execute(
            "SELECT * FROM spaces WHERE id = ?", (space_id,)
        ).fetchone()

        if not space_row:
            raise HTTPException(status_code=404,
                                detail=f"DAO '{space_id}' not yet ingested into DB.")

        stats = _compute_dao_stats(space_id, conn)

        # Top 5 proposals by vote count with silence stats
        top_proposals_rows = conn.execute("""
            SELECT p.id, p.title, p.state, p.votes_count, p.scores_json,
                   p.scores_total, p.link, p.start_ts, p.end_ts,
                   COUNT(DISTINCT fp.username) as forum_posters
            FROM proposals p
            LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
            WHERE p.space_id = ?
            GROUP BY p.id
            ORDER BY p.votes_count DESC
            LIMIT 5
        """, (space_id,)).fetchall()

        top_proposals = []
        for p in top_proposals_rows:
            votes = p["votes_count"] or 0
            posters = p["forum_posters"] or 0
            scores = json.loads(p["scores_json"]) if p["scores_json"] else []
            score_total = p["scores_total"] or 0
            top_share = (max(scores) / score_total * 100) if score_total > 0 and scores else None

            top_proposals.append({
                "id": p["id"],
                "title": p["title"],
                "state": p["state"],
                "votes_count": votes,
                "forum_posters": posters,
                "silence_ratio_pct": round(posters / votes * 100, 3) if votes > 0 else None,
                "top_choice_share_pct": round(top_share, 1) if top_share is not None else None,
                "link": p["link"],
            })

        dao_name = next(d["name"] for d in CURATED_DAOS if d["id"] == space_id)

        return DAODetail(
            id=space_id,
            name=dao_name,
            network=space_row["network"],
            about=space_row["about"],
            space_snapshot_url=f"https://snapshot.org/#/{space_id}",
            top_proposals=top_proposals,
            **stats,
        )
    finally:
        conn.close()
