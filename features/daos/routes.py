# features/daos/routes.py
"""
GET /daos        — List all curated DAOs with live stats.
GET /daos/{id}   — Single DAO detail with per-proposal silence summary.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.curated_daos import CURATED_DAOS
from db.schema import get_connection
from features.daos.service import compute_dao_stats, get_space, top_proposals

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
            space_row = get_space(conn, dao["id"])
            results.append(DAOSummary(
                id=dao["id"],
                name=dao["name"],
                network=space_row["network"] if space_row else None,
                about=space_row["about"] if space_row else None,
                **compute_dao_stats(conn, dao["id"]),
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
    known_ids = {dao["id"] for dao in CURATED_DAOS}
    if space_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"DAO '{space_id}' not in curated list. "
                   f"Valid IDs: {sorted(known_ids)}"
        )

    conn = get_connection()
    try:
        space_row = get_space(conn, space_id)
        if not space_row:
            raise HTTPException(status_code=404,
                                detail=f"DAO '{space_id}' not yet ingested into DB.")

        dao_name = next(d["name"] for d in CURATED_DAOS if d["id"] == space_id)

        return DAODetail(
            id=space_id,
            name=dao_name,
            network=space_row["network"],
            about=space_row["about"],
            space_snapshot_url=f"https://snapshot.org/#/{space_id}",
            top_proposals=top_proposals(conn, space_id),
            **compute_dao_stats(conn, space_id),
        )
    finally:
        conn.close()
