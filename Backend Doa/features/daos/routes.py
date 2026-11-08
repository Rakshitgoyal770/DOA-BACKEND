# features/daos/routes.py
"""
features/daos/routes.py — The /daos HTTP endpoints.

WHAT THIS FILE DOES
    GET /daos              every curated DAO with its aggregated numbers
    GET /daos/{space_id}   one DAO with its five most-voted proposals
    HTTP layer only: the numbers come from features/daos/service.py.

WHERE IT SITS
    client --HTTP--> main.py --> THIS FILE --> features/daos/service.py
                                           --> features/metrics.py --> SQLite

INPUTS
    space_id (URL path) — must be one of config/curated_daos.py.
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
    forum_coverage_pct: float          # % of proposals with at least one forum post
    avg_silence_ratio_pct: float       # mean of forum posters ÷ voters across proposals
    avg_top_choice_share_pct: float    # mean winning-choice share across proposals


class DAODetail(DAOSummary):
    space_snapshot_url: str
    top_proposals: list[dict]          # top 5 by vote count with silence ratio


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DAOSummary], summary="List all curated DAOs")
def list_daos():
    """
    Returns all curated DAOs with aggregated governance stats:
    - Forum coverage (% of proposals with forum discussion)
    - Average silence ratio (forum posters vs. voters)
    - Average winning-choice share (how one-sided votes are)
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
    Full detail for one DAO, including its 5 most-voted proposals, each with its
    silence ratio and winning-choice share. Use the `space_id` values from GET /daos
    (e.g. `arbitrumfoundation.eth`).
    """
    known_ids = {dao["id"] for dao in CURATED_DAOS}
    if space_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"DAO '{space_id}' not in curated list. Valid IDs: {sorted(known_ids)}"
        )

    conn = get_connection()
    try:
        space_row = get_space(conn, space_id)
        if not space_row:
            raise HTTPException(status_code=404,
                                detail=f"DAO '{space_id}' not yet synced. Run: python -m features.sync.runner --sync-all")

        return DAODetail(
            id=space_id,
            name=next(d["name"] for d in CURATED_DAOS if d["id"] == space_id),
            network=space_row["network"],
            about=space_row["about"],
            space_snapshot_url=f"https://snapshot.org/#/{space_id}",
            top_proposals=top_proposals(conn, space_id),
            **compute_dao_stats(conn, space_id),
        )
    finally:
        conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# The response model is returned as JSON and the request ends. To see how each
# number is computed, read features/daos/service.py, then features/metrics.py.
# If the DAO is not curated: 404 listing the valid ids.
# If it is curated but its space row is missing: 404 asking for a sync
#   (features/proposals/fetch.py refresh_spaces writes that row).
