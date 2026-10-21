# features/chat/context.py
"""
Merges SQL facts with retrieved vector chunks so the LLM sees both:

  * PROPOSAL FACTS  - result, scores, turnout, silence ratio, whale share (from SQLite)
  * enriched sources - for forum posts, who the author is on-chain: linked wallet,
                       link confidence, ENS name, voting power and how they voted

The vector store only knows text and index-time metadata; everything here is
looked up live, so new votes and new identity links show up without re-embedding.
"""

import json

MAX_PROPOSALS = 3          # keep the prompt inside free-tier token limits
TOP_N_WHALES = 4


def _decode_choice(choice_json: str | None, choices: list) -> str | None:
    """'[1]' -> 'FOR'; '[1, 4]' -> 'FOR, Option 4'; dict (weighted) -> compact text."""
    if not choice_json:
        return None
    try:
        raw = json.loads(choice_json)
    except (TypeError, ValueError):
        return str(choice_json)

    def name(i):
        return choices[i - 1] if isinstance(i, int) and 0 < i <= len(choices) else str(i)

    if isinstance(raw, int):
        return name(raw)
    if isinstance(raw, list):
        return ", ".join(name(i) for i in raw)
    if isinstance(raw, dict):
        return ", ".join(f"{name(int(k)) if str(k).isdigit() else k}: {v}" for k, v in raw.items())
    return str(raw)


def _fmt_vp(vp: float | None) -> str | None:
    if vp is None:
        return None
    for unit, div in (("M", 1e6), ("K", 1e3)):
        if vp >= div:
            return f"{vp / div:.1f}{unit}"
    return f"{vp:.1f}"


def proposal_facts(conn, proposal_id: str) -> dict | None:
    """Structured facts about one proposal, or None if it is not in SQLite."""
    p = conn.execute(
        """
        SELECT p.id, p.title, p.state, p.choices_json, p.scores_json, p.scores_total,
               p.votes_count, p.start_ts, p.end_ts, s.name AS dao
        FROM proposals p LEFT JOIN spaces s ON s.id = p.space_id WHERE p.id = ?
        """,
        (proposal_id,),
    ).fetchone()
    if not p:
        return None

    choices = json.loads(p["choices_json"]) if p["choices_json"] else []
    scores = json.loads(p["scores_json"]) if p["scores_json"] else []
    total = p["scores_total"] or sum(scores) or 0
    results = [
        {"choice": c, "score": round(sc, 2), "share_pct": round(100 * sc / total, 1) if total else None}
        for c, sc in zip(choices, scores)
    ]
    winner = max(results, key=lambda r: r["score"])["choice"] if results else None

    posters = conn.execute(
        "SELECT COUNT(DISTINCT lower(username)) FROM forum_posts WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()[0]
    votes_count = p["votes_count"]
    silence_pct = round(100 * posters / votes_count, 3) if votes_count else None

    vp_rows = conn.execute(
        "SELECT vp FROM votes WHERE proposal_id = ? ORDER BY vp DESC", (proposal_id,)
    ).fetchall()
    top_share = None
    if vp_rows:
        loaded_vp = sum(r["vp"] or 0 for r in vp_rows)
        partial = bool(votes_count) and len(vp_rows) < votes_count
        # With partial votes, measure against the full tally so the share is not inflated.
        all_vp = (total if partial and total else loaded_vp)
        top_share = round(100 * sum(r["vp"] or 0 for r in vp_rows[:TOP_N_WHALES]) / all_vp, 1) if all_vp else None

    return {
        "proposal_id": p["id"],
        "dao": p["dao"],
        "title": p["title"],
        "state": p["state"],
        "winning_choice": winner,
        "results": results,
        "total_voters": votes_count,
        "forum_posters": posters,
        "silence_ratio_pct": silence_pct,
        f"top_{TOP_N_WHALES}_voters_share_pct": top_share,
        "votes_loaded": len(vp_rows),
        "votes_partial": bool(votes_count) and len(vp_rows) < votes_count,
    }


def format_facts(f: dict) -> str:
    """Compact, LLM-readable text for one proposal's facts."""
    lines = [f"- {f['dao']} | \"{f['title']}\" | state: {f['state']}"]
    if f["results"]:
        res = "; ".join(f"{r['choice']} {r['share_pct']}%" for r in f["results"] if r["share_pct"] is not None)
        lines.append(f"  result: {res} (winner: {f['winning_choice']})")
    lines.append(f"  voters: {f['total_voters']}; forum posters: {f['forum_posters']}"
                 + (f" (silence ratio {f['silence_ratio_pct']}%)" if f["silence_ratio_pct"] is not None else ""))
    top = f.get(f"top_{TOP_N_WHALES}_voters_share_pct")
    if top is not None:
        note = f" (at least; only {f['votes_loaded']} of {f['total_voters']} votes loaded)" if f["votes_partial"] else ""
        lines.append(f"  top {TOP_N_WHALES} loaded voters hold {top}% of total voting power{note}")
    return "\n".join(lines)


def author_context(conn, proposal_id: str | None, username: str | None) -> dict:
    """On-chain identity of a forum author for a given proposal (empty if unlinked)."""
    if not username:
        return {}
    ident = conn.execute(
        "SELECT wallet_address, confidence_level, resolution_method FROM resolved_identities "
        "WHERE forum_username = ?",
        (username.lower(),),
    ).fetchone()
    if not ident:
        return {}
    wallet = ident["wallet_address"]
    ens = conn.execute(
        "SELECT ens_name FROM wallet_ens WHERE lower(wallet_address) = ? AND verified = 1", (wallet.lower(),)
    ).fetchone()
    ctx = {
        "wallet": wallet,
        "ens_name": ens["ens_name"] if ens else None,
        "link_confidence": ident["confidence_level"],
        "link_method": ident["resolution_method"],
    }
    if proposal_id:
        vote = conn.execute(
            "SELECT v.vp, v.choice_json, p.choices_json FROM votes v JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.proposal_id = ? AND lower(v.voter) = ?",
            (proposal_id, wallet.lower()),
        ).fetchone()
        if vote:
            choices = json.loads(vote["choices_json"]) if vote["choices_json"] else []
            ctx["voting_power"] = vote["vp"]
            ctx["voted"] = _decode_choice(vote["choice_json"], choices)
    return ctx


def enrich_chunks(conn, chunks: list[dict]) -> list[dict]:
    """Adds chunk['sql'] = author on-chain context to forum-post chunks."""
    for c in chunks:
        meta = c["metadata"]
        c["sql"] = (author_context(conn, meta.get("proposal_id"), meta.get("author"))
                    if meta.get("source_type") == "forum_post" else {})
    return chunks


def collect_facts(conn, chunks: list[dict], max_proposals: int = MAX_PROPOSALS) -> list[dict]:
    """Facts for the distinct proposals behind the chunks, in order of best match."""
    seen, facts = set(), []
    for c in chunks:
        pid = c["metadata"].get("proposal_id")
        if pid and pid not in seen:
            seen.add(pid)
            f = proposal_facts(conn, pid)
            if f:
                facts.append(f)
        if len(facts) >= max_proposals:
            break
    return facts


def source_label(i: int, c: dict) -> str:
    """'[Source 2 - forum_post by Zeptimus (zeptimus.eth, voting power 1.2M, voted AGAINST; link: high)]'."""
    meta, sql = c["metadata"], c.get("sql") or {}
    label = f"Source {i} - {meta.get('source_type')}"
    if meta.get("author"):
        label += f" by {meta['author']}"
        if sql:
            bits = []
            if sql.get("ens_name"):
                bits.append(sql["ens_name"])
            if sql.get("voting_power") is not None:
                bits.append(f"voting power {_fmt_vp(sql['voting_power'])}")
            if sql.get("voted"):
                bits.append(f"voted {sql['voted']}")
            bits.append(f"wallet link: {sql['link_confidence']}")
            label += f" ({', '.join(bits)})"
        else:
            label += " (wallet unknown)"
    return label
