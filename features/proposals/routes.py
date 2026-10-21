# features/proposals/routes.py
"""
GET /proposals                    — List proposals with filters and governance stats.
GET /proposals/{proposal_id}      — Full proposal detail with vote concentration.
GET /proposals/{proposal_id}/concentration  — Top-N voter whale analysis.
"""

import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.schema import get_connection
from features.proposals import service

router = APIRouter(prefix="/proposals", tags=["Proposals"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ProposalSummary(BaseModel):
    id: str
    space_id: str
    title: str
    state: str | None
    votes_count: int | None
    forum_posters: int
    silence_ratio_pct: float | None     # forum_posters / votes_count as %
    top_choice_share_pct: float | None  # winning choice % of total weight
    scores_total: float | None
    link: str | None
    discussion_url: str | None
    author: str | None
    start_ts: int | None
    end_ts: int | None


class VoterEntry(BaseModel):
    voter: str
    voting_power: float
    power_share_pct: float
    choice: str | int | dict | list     # Snapshot choice can be any of these


class ConcentrationReport(BaseModel):
    proposal_id: str
    title: str
    total_voters_ingested: int
    total_voting_power: float
    top_n: int
    top_n_power: float
    top_n_share_pct: float              # the headline whale stat
    top_voters: list[VoterEntry]
    note: str


class ProposalDetail(ProposalSummary):
    body_preview: str                   # first 500 chars of proposal body
    choices: list[str]
    scores: list[float]
    votes_ingested: int                 # how many individual votes are in our DB


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProposalSummary], summary="List proposals")
def list_proposals(
    space_id: str | None = Query(default=None,
                                  description="Filter by DAO, e.g. arbitrumfoundation.eth"),
    state: str | None = Query(default=None,
                               description="Filter by state: active | closed | pending"),
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
):
    """
    Returns proposals with silence and concentration metrics pre-computed.

    Key fields:
    - `silence_ratio_pct`: % of voters who also posted in the forum discussion.
      Values below 1% indicate the vote was decided largely without public deliberation.
    - `top_choice_share_pct`: % of total voting weight captured by the winning choice.
      Values near 100% indicate a one-sided, uncontested vote.
    """
    conn = get_connection()
    try:
        rows = service.list_proposals(conn, space_id, state, limit, skip)

        return [
            ProposalSummary(
                id=r["id"],
                space_id=r["space_id"],
                title=r["title"],
                state=r["state"],
                votes_count=r["votes_count"],
                forum_posters=r["forum_posters"],
                silence_ratio_pct=service.silence_ratio(r["votes_count"], r["forum_posters"]),
                top_choice_share_pct=service.top_choice_share(r["scores_json"], r["scores_total"]),
                scores_total=r["scores_total"],
                link=r["link"],
                discussion_url=r["discussion_url"],
                author=r["author"],
                start_ts=r["start_ts"],
                end_ts=r["end_ts"],
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{proposal_id}", response_model=ProposalDetail,
            summary="Full proposal detail")
def get_proposal(proposal_id: str):
    """
    Returns full proposal including body preview, vote breakdown, and
    counts of forum participants and ingested individual votes.
    """
    conn = get_connection()
    try:
        found = service.get_proposal(conn, proposal_id)
        if not found:
            raise HTTPException(status_code=404,
                                detail=f"Proposal '{proposal_id}' not found.")
        row, votes_ingested = found

        choices = json.loads(row["choices_json"]) if row["choices_json"] else []
        scores = json.loads(row["scores_json"]) if row["scores_json"] else []
        body = row["body"] or ""

        return ProposalDetail(
            id=row["id"],
            space_id=row["space_id"],
            title=row["title"],
            state=row["state"],
            votes_count=row["votes_count"],
            forum_posters=row["forum_posters"],
            silence_ratio_pct=service.silence_ratio(row["votes_count"], row["forum_posters"]),
            top_choice_share_pct=service.top_choice_share(row["scores_json"], row["scores_total"]),
            scores_total=row["scores_total"],
            link=row["link"],
            discussion_url=row["discussion_url"],
            author=row["author"],
            start_ts=row["start_ts"],
            end_ts=row["end_ts"],
            body_preview=body[:500] + ("..." if len(body) > 500 else ""),
            choices=choices,
            scores=scores,
            votes_ingested=votes_ingested,
        )
    finally:
        conn.close()


@router.get("/{proposal_id}/concentration", response_model=ConcentrationReport,
            summary="Whale concentration analysis")
def get_concentration(
    proposal_id: str,
    top_n: int = Query(default=4, ge=1, le=50,
                       description="How many top voters to analyze (default 4)")
):
    """
    Computes the voting power concentration for a proposal.

    Returns the top-N voters by voting power and their combined share of
    total weight — the core 'whale' metric of this platform.

    Example: top_n=4 showing 84% means 4 wallets controlled 84% of the outcome.

    Note: Individual votes are only available for proposals where
    `votes_ingested > 0` (use GET /proposals/{id} to check).
    Ingest votes first via the ingestion pipeline if this returns an empty list.
    """
    conn = get_connection()
    try:
        report = service.concentration(conn, proposal_id, top_n)
        if report is None:
            raise HTTPException(status_code=404,
                                detail=f"Proposal '{proposal_id}' not found.")
        if report["total_voters_ingested"] == 0:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No individual votes ingested for proposal '{proposal_id}'. "
                    "Run the vote ingestion pipeline first."
                )
            )
        return ConcentrationReport(
            proposal_id=proposal_id,
            top_n=top_n,
            top_voters=[VoterEntry(**v) for v in report.pop("top_voters")],
            **report,
        )
    finally:
        conn.close()
