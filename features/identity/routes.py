# features/identity/routes.py
"""
Identity linking endpoints for the frontend: forum-user -> wallet links with
confidence, per-proposal participants (who spoke, who voted, who is linked),
coverage stats, and a trigger to run the linking strategies.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from db.schema import get_connection
from features.identity.common import CONFIDENCE_RANK
from features.identity.runner import resolve_all
from features.identity.stats import identity_stats

router = APIRouter(prefix="/identities", tags=["Identity Linking"])

# State of the last background resolution run, shown by GET /identities/resolve/status
_run_state: dict = {"status": "idle", "started_at": None, "finished_at": None, "result": None, "error": None}


def _min_rank_clause(min_confidence: str | None) -> tuple[str, list]:
    """SQL fragment keeping links at or above `min_confidence`."""
    if not min_confidence:
        return "", []
    if min_confidence not in CONFIDENCE_RANK:
        raise HTTPException(status_code=422, detail=f"min_confidence must be one of {list(CONFIDENCE_RANK)}")
    allowed = [c for c, r in CONFIDENCE_RANK.items() if r >= CONFIDENCE_RANK[min_confidence]]
    return f"r.confidence_level IN ({','.join('?' * len(allowed))})", allowed


@router.get("/stats", summary="Coverage of forum-user -> wallet links")
def get_identity_stats():
    """Users and posts linked, medium-or-better share, posts carrying voting power,
    plus breakdowns by method and confidence. Use for a coverage widget."""
    conn = get_connection()
    try:
        stats = identity_stats(conn)
        stats["by_dao"] = [
            dict(r) for r in conn.execute(
                """
                SELECT s.id AS space_id, s.name,
                       COUNT(DISTINCT lower(f.username)) AS forum_users,
                       COUNT(DISTINCT r.forum_username) AS linked_users
                FROM spaces s
                JOIN proposals p ON p.space_id = s.id
                JOIN forum_posts f ON f.proposal_id = p.id
                LEFT JOIN resolved_identities r ON r.forum_username = lower(f.username)
                GROUP BY s.id ORDER BY forum_users DESC
                """
            )
        ]
        return stats
    finally:
        conn.close()


@router.get("", summary="List and search resolved identities")
def list_identities(
    q: str | None = Query(default=None, description="Search username, wallet or ENS name"),
    min_confidence: str | None = Query(default=None, description="low | medium | high | certain (and above)"),
    method: str | None = Query(default=None, description="e.g. ens_username, voter_ens, self_disclosed"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    clauses, params = [], []
    conf_sql, conf_params = _min_rank_clause(min_confidence)
    if conf_sql:
        clauses.append(conf_sql)
        params += conf_params
    if method:
        clauses.append("r.resolution_method = ?")
        params.append(method)
    if q:
        clauses.append(
            "(r.forum_username LIKE ? OR lower(r.wallet_address) LIKE ? OR lower(IFNULL(w.ens_name, '')) LIKE ?)"
        )
        like = f"%{q.lower()}%"
        params += [like, like, like]
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = get_connection()
    try:
        base = f"""
            FROM resolved_identities r
            LEFT JOIN wallet_ens w ON lower(w.wallet_address) = lower(r.wallet_address) AND w.verified = 1
            {where}
        """
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT r.forum_username, r.wallet_address, r.confidence_level, r.resolution_method,
                   r.resolved_at, w.ens_name,
                   (SELECT COUNT(*) FROM forum_posts f WHERE lower(f.username) = r.forum_username) AS post_count
            {base} ORDER BY r.resolved_at DESC LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/proposal/{proposal_id}", summary="Forum participants of a proposal with wallet, confidence and voting power")
def proposal_participants(proposal_id: str):
    """Everyone who posted on a proposal's forum thread: their post count, linked wallet
    and confidence (null if unlinked), and the voting power and choice if that wallet voted.
    Also returns the share of forum posters we could identify."""
    conn = get_connection()
    try:
        prop = conn.execute(
            "SELECT id, title, space_id, votes_count FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Proposal not found")
        rows = conn.execute(
            """
            SELECT lower(f.username) AS username, COUNT(*) AS posts,
                   r.wallet_address, r.confidence_level, r.resolution_method,
                   w.ens_name, v.vp AS voting_power, v.choice_json
            FROM forum_posts f
            LEFT JOIN resolved_identities r ON r.forum_username = lower(f.username)
            LEFT JOIN wallet_ens w ON lower(w.wallet_address) = lower(r.wallet_address) AND w.verified = 1
            LEFT JOIN votes v ON v.proposal_id = f.proposal_id AND lower(v.voter) = lower(r.wallet_address)
            WHERE f.proposal_id = ?
            GROUP BY lower(f.username)
            ORDER BY (v.vp IS NULL), v.vp DESC, posts DESC
            """,
            (proposal_id,),
        ).fetchall()
        participants = []
        for r in rows:
            d = dict(r)
            raw_choice = d.pop("choice_json", None)
            d["choice"] = json.loads(raw_choice) if raw_choice else None
            participants.append(d)
        linked = sum(1 for p in participants if p["wallet_address"])
        voted = sum(1 for p in participants if p["voting_power"] is not None)
        return {
            "proposal_id": prop["id"],
            "title": prop["title"],
            "space_id": prop["space_id"],
            "total_voters": prop["votes_count"],
            "forum_posters": len(participants),
            "linked_posters": linked,
            "linked_pct": round(100 * linked / len(participants), 1) if participants else 0.0,
            "posters_who_voted": voted,
            "participants": participants,
        }
    finally:
        conn.close()


@router.get("/wallet/{wallet_address}", summary="Reverse lookup: forum user(s) for a wallet")
def wallet_identity(wallet_address: str):
    """Which forum username (if any) is linked to this wallet, with its cached ENS name."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM resolved_identities WHERE lower(wallet_address) = ?", (wallet_address.lower(),)
        ).fetchall()
        ens = conn.execute(
            "SELECT ens_name, verified FROM wallet_ens WHERE lower(wallet_address) = ?", (wallet_address.lower(),)
        ).fetchone()
        return {
            "wallet_address": wallet_address,
            "ens_name": ens["ens_name"] if ens and ens["verified"] else None,
            "forum_users": [dict(r) for r in rows],
        }
    finally:
        conn.close()


@router.get("/resolve/status", summary="Status of the last resolution run")
def resolution_status():
    return _run_state


def _run_resolution(profile_limit: int, voter_wallets: int):
    _run_state.update(status="running", started_at=datetime.now(timezone.utc).isoformat(),
                      finished_at=None, result=None, error=None)
    conn = get_connection()
    try:
        _run_state["result"] = resolve_all(conn, profile_limit=profile_limit, voter_wallets=voter_wallets)
        _run_state["status"] = "done"
    except Exception as e:  # surfaced to the frontend through /resolve/status
        _run_state.update(status="failed", error=str(e))
    finally:
        _run_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        conn.close()


@router.post("/resolve", summary="Run all identity-linking strategies")
def run_resolution(
    background_tasks: BackgroundTasks,
    profile_limit: int = Query(default=100, ge=1, le=500, description="Discourse profiles to scan"),
    voter_wallets: int = Query(default=300, ge=1, le=2000, description="Top voter wallets to reverse-resolve"),
):
    """Starts in the background (it calls ENS and Discourse). Poll GET /identities/resolve/status."""
    if _run_state["status"] == "running":
        raise HTTPException(status_code=409, detail="A resolution run is already in progress")
    background_tasks.add_task(_run_resolution, profile_limit, voter_wallets)
    return {"status": "started", "poll": "GET /identities/resolve/status"}


@router.get("/{username}", summary="Wallet link and voting history for one forum user")
def get_identity(username: str):
    """The resolved wallet for a forum username, its ENS name, post count, and voting power per proposal."""
    conn = get_connection()
    try:
        ident = conn.execute(
            "SELECT * FROM resolved_identities WHERE forum_username = ?", (username.lower(),)
        ).fetchone()
        if not ident:
            raise HTTPException(status_code=404, detail=f"No wallet linked to '{username}'")
        ens = conn.execute(
            "SELECT ens_name FROM wallet_ens WHERE lower(wallet_address) = ? AND verified = 1",
            (ident["wallet_address"].lower(),),
        ).fetchone()
        posts = conn.execute(
            "SELECT COUNT(*) FROM forum_posts WHERE lower(username) = ?", (username.lower(),)
        ).fetchone()[0]
        votes = conn.execute(
            """
            SELECT v.proposal_id, p.title, v.vp, v.choice_json
            FROM votes v JOIN proposals p ON p.id = v.proposal_id
            WHERE lower(v.voter) = ? ORDER BY v.vp DESC LIMIT 25
            """,
            (ident["wallet_address"].lower(),),
        ).fetchall()
        return {
            **dict(ident),
            "ens_name": ens["ens_name"] if ens else None,
            "post_count": posts,
            "votes": [dict(v) for v in votes],
        }
    finally:
        conn.close()
