# api/routes_proposal.py
"""
GET /proposals                    — List proposals with filters and governance stats.
GET /proposals/{proposal_id}      — Full proposal detail with vote concentration.
GET /proposals/{proposal_id}/concentration  — Top-N voter whale analysis.
"""

import json
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.schema import get_connection

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _silence_ratio(votes_count: int | None, forum_posters: int) -> float | None:
    if votes_count and votes_count > 0:
        return round(forum_posters / votes_count * 100, 3)
    return None


def _top_choice_share(scores_json: str | None, scores_total: float | None) -> float | None:
    if not scores_json or not scores_total or scores_total == 0:
        return None
    try:
        scores = json.loads(scores_json)
        return round(max(scores) / scores_total * 100, 1) if scores else None
    except Exception:
        return None


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
        where_clauses = []
        params: list = []

        if space_id:
            where_clauses.append("p.space_id = ?")
            params.append(space_id)
        if state:
            where_clauses.append("p.state = ?")
            params.append(state)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = conn.execute(f"""
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

        return [
            ProposalSummary(
                id=r["id"],
                space_id=r["space_id"],
                title=r["title"],
                state=r["state"],
                votes_count=r["votes_count"],
                forum_posters=r["forum_posters"],
                silence_ratio_pct=_silence_ratio(r["votes_count"], r["forum_posters"]),
                top_choice_share_pct=_top_choice_share(r["scores_json"], r["scores_total"]),
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
        row = conn.execute("""
            SELECT p.*, COUNT(DISTINCT fp.username) as forum_posters
            FROM proposals p
            LEFT JOIN forum_posts fp ON fp.proposal_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
        """, (proposal_id,)).fetchone()

        if not row:
            raise HTTPException(status_code=404,
                                detail=f"Proposal '{proposal_id}' not found.")

        votes_ingested = conn.execute(
            "SELECT COUNT(*) as c FROM votes WHERE proposal_id = ?",
            (proposal_id,)
        ).fetchone()["c"]

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
            silence_ratio_pct=_silence_ratio(row["votes_count"], row["forum_posters"]),
            top_choice_share_pct=_top_choice_share(row["scores_json"], row["scores_total"]),
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
        title_row = conn.execute(
            "SELECT title, choices_json FROM proposals WHERE id = ?",
            (proposal_id,)
        ).fetchone()

        if not title_row:
            raise HTTPException(status_code=404,
                                detail=f"Proposal '{proposal_id}' not found.")

        choices = json.loads(title_row["choices_json"]) if title_row["choices_json"] else []

        all_votes = conn.execute("""
            SELECT voter, vp, choice_json
            FROM votes
            WHERE proposal_id = ?
            ORDER BY vp DESC
        """, (proposal_id,)).fetchall()

        if not all_votes:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No individual votes ingested for proposal '{proposal_id}'. "
                    "Run the vote ingestion pipeline first."
                )
            )

        total_vp = sum(v["vp"] for v in all_votes if v["vp"])
        top_votes = all_votes[:top_n]
        top_vp = sum(v["vp"] for v in top_votes if v["vp"])

        def _decode_choice(choice_json: str, choices: list) -> str | int | dict | list:
            try:
                raw = json.loads(choice_json)
                # Snapshot uses 1-indexed integers for single choice
                if isinstance(raw, int) and 0 < raw <= len(choices):
                    return choices[raw - 1]
                return raw
            except Exception:
                return choice_json

        top_voter_entries = [
            VoterEntry(
                voter=v["voter"],
                voting_power=round(v["vp"], 4),
                power_share_pct=round(v["vp"] / total_vp * 100, 2) if total_vp else 0,
                choice=_decode_choice(v["choice_json"], choices),
            )
            for v in top_votes
        ]

        return ConcentrationReport(
            proposal_id=proposal_id,
            title=title_row["title"],
            total_voters_ingested=len(all_votes),
            total_voting_power=round(total_vp, 2),
            top_n=top_n,
            top_n_power=round(top_vp, 2),
            top_n_share_pct=round(top_vp / total_vp * 100, 1) if total_vp else 0,
            top_voters=top_voter_entries,
            note=(
                f"Vote data covers the first 1000 votes ingested (ordered by creation time). "
                f"Whale concentration may be higher if large holders voted later."
            ),
        )
    finally:
        conn.close()
