# features/proposals/routes.py
"""
features/proposals/routes.py — The /proposals HTTP endpoints.

WHAT THIS FILE DOES
    GET /proposals                             list proposals (filter, page)
    GET /proposals/{proposal_id}               one proposal in detail
    GET /proposals/{proposal_id}/concentration whale report: largest wallets
    This is the HTTP layer only: it validates input (FastAPI does that from the
    function signatures), opens a database connection, asks
    features/proposals/service.py for the data, and shapes the JSON response.

WHERE IT SITS
    client --HTTP--> main.py (router registered there) --> THIS FILE
          --> features/proposals/service.py --> features/metrics.py --> SQLite

INPUTS
    Path and query parameters of the request (documented on each endpoint and
    shown at /docs). The database connection is opened here per request.
"""

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.schema import get_connection
from features.metrics import proposal_status, silence_ratio_pct, winning_share_pct
from features.proposals import service

router = APIRouter(prefix="/proposals", tags=["Proposals"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ProposalSummary(BaseModel):
    id: str
    space_id: str
    title: str
    state: str | None                   # Snapshot's label as of our last sync (can be out of date)
    status: str                         # upcoming | open | ended_unsettled | closed | unknown, from the dates and the clock
    votes_count: int | None
    forum_posters: int
    silence_ratio_pct: float | None     # forum posters as % of voters
    top_choice_share_pct: float | None  # winning choice % of total voting power
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
    choice: str | int | dict | list | None   # names: "For", ["For", "Option D"], {"For": 2}


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


def _summary_fields(row) -> dict:
    """
    The ProposalSummary fields of one proposal row (shared by list and detail).

    Parameter (where it comes from):
        row - a proposals row with a `forum_posters` column, returned by
              service.list_proposals or service.get_proposal.
    """
    return {
        "id": row["id"],
        "space_id": row["space_id"],
        "title": row["title"],
        "state": row["state"],
        "status": proposal_status(row)["status"],
        "votes_count": row["votes_count"],
        "forum_posters": row["forum_posters"],
        "silence_ratio_pct": silence_ratio_pct(row["forum_posters"], row["votes_count"]),
        "top_choice_share_pct": winning_share_pct(row["scores_json"], row["scores_total"]),
        "scores_total": row["scores_total"],
        "link": row["link"],
        "discussion_url": row["discussion_url"],
        "author": row["author"],
        "start_ts": row["start_ts"],
        "end_ts": row["end_ts"],
    }


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
    - `silence_ratio_pct`: forum posters as a % of voters. Below 1% means the
      vote was decided largely without public deliberation.
    - `top_choice_share_pct`: % of total voting power captured by the winning
      choice. Near 100% means a one-sided, uncontested vote.
    """
    conn = get_connection()
    try:
        rows = service.list_proposals(conn, space_id, state, limit, skip)
        return [ProposalSummary(**_summary_fields(r)) for r in rows]
    finally:
        conn.close()


@router.get("/{proposal_id}", response_model=ProposalDetail, summary="Full proposal detail")
def get_proposal(proposal_id: str):
    """
    Returns full proposal including body preview, vote breakdown, and counts of
    forum participants and stored individual votes.
    """
    conn = get_connection()
    try:
        found = service.get_proposal(conn, proposal_id)
        if not found:
            raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found.")
        row, votes_ingested = found
        body = row["body"] or ""
        return ProposalDetail(
            **_summary_fields(row),
            body_preview=body[:500] + ("..." if len(body) > 500 else ""),
            choices=json.loads(row["choices_json"]) if row["choices_json"] else [],
            scores=json.loads(row["scores_json"]) if row["scores_json"] else [],
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
    Voting-power concentration: the top-N wallets and their combined share of
    all voting power. Example: top_n=4 showing 54% means 4 wallets held 54%.
    """
    conn = get_connection()
    try:
        report = service.concentration(conn, proposal_id, top_n)
        if report is None:
            raise HTTPException(status_code=404, detail=f"Proposal '{proposal_id}' not found.")
        if report["total_voters_ingested"] == 0:
            raise HTTPException(
                status_code=404,
                detail=(f"No individual votes ingested for proposal '{proposal_id}'. "
                        "Run: python -m features.sync.runner --fetch-votes"),
            )
        return ConcentrationReport(
            proposal_id=proposal_id,
            top_n=top_n,
            top_voters=[VoterEntry(**v) for v in report.pop("top_voters")],
            **report,
        )
    finally:
        conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# Each endpoint returns its response model; FastAPI turns it into JSON and the
# request is finished. Data comes from features/proposals/service.py (read it next
# to see the queries) and the formulas from features/metrics.py.
# If the proposal id is unknown: HTTP 404.
# If the client sends invalid parameters (e.g. limit=500): FastAPI answers 422
#   before this code runs.
