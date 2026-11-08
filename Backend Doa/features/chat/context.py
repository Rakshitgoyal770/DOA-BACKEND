# features/chat/context.py
"""
features/chat/context.py — Database facts about ONE proposal or ONE forum author.

WHAT THIS FILE DOES
    Small, tested building blocks that read SQLite (never the LLM):
      * proposal_facts   one proposal: result per choice, winner, voters, forum posters,
                         silence ratio (forum posters / voters), top-4 voting-power share
      * author_context   who a forum author is on-chain: linked wallet, ENS name, how
                         confident the link is, and (for one proposal) how much voting
                         power they used and what they voted
      * enrich_chunks    author_context() for every forum-post chunk a search returned
      * source_label     the header line of one source in the writer's prompt
    Which of these run for a question is decided by the agent
    (features/chat/agent.py), through the lookups in features/chat/tools.py.

WHERE IT SITS
    features/chat/tools.py  (proposal_details, person, search_forum)  --> THIS FILE
    features/chat/prompt.py (source_label)                            --> THIS FILE
    The formulas live in features/metrics.py, so the chat, /proposals and /daos
    always agree.

INPUTS
    conn   - SQLite connection opened by the caller (agent.py gather_evidence, or a test).
    chunks - list returned by retrieval.retrieve(): each has "id", "document",
             "distance" and "metadata" (source_type, proposal_id, author, ...).
"""

import json

from features.identity.common import verified_ens_name
from features.metrics import (choice_text, count_forum_posters, decode_choice,
                              silence_ratio_pct, top_voter_share)

TOP_N_WHALES = 4           # the "top-N wallets" share reported in the facts


def _fmt_vp(vp: float | None) -> str | None:
    """Voting power as short text for the prompt: 1234567 -> '1.2M', 1500 -> '1.5K'."""
    if vp is None:
        return None
    for unit, div in (("M", 1e6), ("K", 1e3)):
        if vp >= div:
            return f"{vp / div:.1f}{unit}"
    return f"{vp:.1f}"


def proposal_facts(conn, proposal_id: str) -> dict | None:
    """
    Structured facts about one proposal, or None if it is not in SQLite.

    Parameters (where they come from):
        conn        - opened by the caller.
        proposal_id - chosen by the agent (tools.proposal_details), usually taken from
                      tools.find_proposals; or a test.

    Returns: dao, title, state, results (choice / score / share %), winning_choice,
    total_voters, forum_posters, silence_ratio_pct, top_4_voters_share_pct,
    votes_loaded, votes_partial.
    """
    p = conn.execute(
        """
        SELECT p.id, p.title, p.state, p.choices_json, p.scores_json, p.scores_total,
               p.votes_count, s.name AS dao
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
    posters = count_forum_posters(conn, proposal_id)
    whales = top_voter_share(conn, proposal_id, TOP_N_WHALES)

    return {
        "proposal_id": p["id"],
        "dao": p["dao"],
        "title": p["title"],
        "state": p["state"],
        "winning_choice": max(results, key=lambda r: r["score"])["choice"] if results else None,
        "results": results,
        "total_voters": p["votes_count"],
        "forum_posters": posters,
        "silence_ratio_pct": silence_ratio_pct(posters, p["votes_count"]),
        f"top_{TOP_N_WHALES}_voters_share_pct": whales["top_n_share_pct"] if whales["stored_votes"] else None,
        "votes_loaded": whales["stored_votes"],
        "votes_partial": whales["partial"],
    }


def author_context(conn, proposal_id: str | None, username: str | None) -> dict:
    """
    Who a forum author is on-chain, for one proposal. Empty dict if not linked.

    Parameters (where they come from):
        conn        - opened by the caller.
        proposal_id - the chunk's metadata["proposal_id"] (via enrich_chunks).
        username    - the chunk's metadata["author"], the Discourse username.

    Returns: wallet, ens_name, link_confidence, link_method, and — if that wallet
    voted on this proposal — voting_power and voted (choice names as text).
    The wallet link itself was made by features/identity/ (see runner.py there).
    """
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
    ctx = {
        "wallet": wallet,
        "ens_name": verified_ens_name(conn, wallet),
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
            ctx["voted"] = choice_text(decode_choice(vote["choice_json"], choices))
    return ctx


def enrich_chunks(conn, chunks: list[dict]) -> list[dict]:
    """
    Adds chunk["sql"] to every chunk: author_context() for forum posts, {} otherwise.

    Parameters (where they come from):
        conn   - opened by the caller (tools.search_forum).
        chunks - the list returned by features/chat/retrieval.retrieve().
    Changes the chunks in place and also returns them.
    """
    for c in chunks:
        meta = c["metadata"]
        c["sql"] = (author_context(conn, meta.get("proposal_id"), meta.get("author"))
                    if meta.get("source_type") == "forum_post" else {})
    return chunks


def source_label(i: int, c: dict) -> str:
    """
    The header line of one source in the prompt, e.g.
    'Source 2 - forum_post by Zeptimus (zeptimus.eth, voting power 1.2M, voted For, wallet link: high), on proposal "Frozen ETH"'.
    The proposal title is there because a search across all proposals mixes them: without it the
    writer cannot tell which proposal a passage (and its author's vote) belongs to.

    Parameters (where they come from):
        i - the source number (1-based), from build_prompt's loop in features/chat/prompt.py.
        c - one chunk after enrich_chunks() (so c["sql"] may hold the author's on-chain data);
            c["proposal_title"] is set by tools.search_forum (proposal-text chunks also carry
            their own title in the index metadata).
    """
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
    title = c.get("proposal_title") or meta.get("title")
    if title:
        label += f', on proposal "{title}"'
    return label


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/tools.py — its lookups call these functions.
# Then:            features/chat/prompt.py — build_prompt() uses source_label().
# If a proposal is not in SQLite: proposal_facts returns None (tools.proposal_details
#   turns that into an error the agent can read and recover from).
# If an author has no wallet link: the label says "(wallet unknown)".
