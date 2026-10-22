# features/metrics.py
"""
features/metrics.py — The governance numbers, each defined in exactly one place.

WHAT THIS FILE DOES
    Every number the API and the chat report about a proposal is computed here:
      * forum posters      how many different people posted in its forum thread
      * silence ratio      forum posters as a % of voters
      * winning share      the winning choice's % of all voting power
      * top-voter share    how much voting power the largest N wallets hold
      * choice names       turning Snapshot's choice numbers ([1, 4]) into names

    Before this file existed the same formulas were written 2-4 times in
    different modules, and two copies disagreed (one counted "Alice" and
    "alice" as two posters, another decided "partial data" with its own rule).
    Now every caller uses these functions, so the DAO endpoints, the proposal
    endpoints and the chat can never report different numbers for the same thing.

WHERE IT SITS
    SQLite (filled by features/*/fetch.py)
        -> THIS FILE (pure calculations + a few small read-only queries)
        -> features/daos/service.py, features/proposals/service.py,
           features/chat/context.py  (the three places that report numbers)

INPUTS
    `conn` is always an open SQLite connection that the CALLER opened with
    db.schema.get_connection() (a route handler, or a test). Nothing here
    opens connections, writes to the database, or calls the network.
"""

import json

from features.votes.completeness import PARTIAL, vote_status

# SQL fragment for "number of different forum posters", used inside the
# proposal queries of features/daos/service.py and features/proposals/service.py
# (they join forum_posts as `fp`). Usernames are compared lower-case, so
# "Alice" and "alice" are one person.
FORUM_POSTERS_SQL = "COUNT(DISTINCT lower(fp.username))"


def count_forum_posters(conn, proposal_id: str) -> int:
    """
    Number of different people who posted in a proposal's forum thread.

    Parameters (where they come from):
        conn        - SQLite connection opened by the calling route / test.
        proposal_id - a Snapshot proposal id; features/chat/context.py passes the
                      id found in a retrieved chunk's metadata.
    Same rule as FORUM_POSTERS_SQL, for callers that need one proposal at a time.
    """
    return conn.execute(
        "SELECT COUNT(DISTINCT lower(username)) FROM forum_posts WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()[0]


def silence_ratio_pct(forum_posters: int, votes_count: int | None, decimals: int | None = 3) -> float | None:
    """
    Forum posters as a percentage of voters, or None if nobody voted.

    Parameters (where they come from):
        forum_posters - from FORUM_POSTERS_SQL in a service query, or count_forum_posters().
        votes_count   - proposals.votes_count, Snapshot's own voter count
                        (stored by features/proposals/fetch.py).
        decimals      - 3 for display; None (unrounded) when the caller averages
                        many proposals and rounds once at the end (features/daos/service.py).
    Example: 17 posters, 63,845 voters -> 0.027 (%).
    """
    if not votes_count:
        return None
    value = 100 * (forum_posters or 0) / votes_count
    return value if decimals is None else round(value, decimals)


def winning_share_pct(scores_json: str | None, scores_total: float | None,
                      decimals: int | None = 1) -> float | None:
    """
    The winning choice's share of all voting power, in %, or None.

    Parameters (where they come from):
        scores_json  - proposals.scores_json: JSON list of voting power per choice,
                       e.g. '[1500.0, 20.0]' (Snapshot "scores").
        scores_total - proposals.scores_total: Snapshot's sum of those scores.
        decimals     - 1 for display; None when the caller averages (see silence_ratio_pct).
    """
    if not scores_json or not scores_total:
        return None
    scores = json.loads(scores_json)
    if not scores:
        return None
    value = 100 * max(scores) / scores_total
    return value if decimals is None else round(value, decimals)


def decode_choice(choice_json: str | None, choices: list[str]):
    """
    Snapshot stores a vote's choice as numbers; return the same shape with names.

        '1'            -> 'For'                       (single choice, 1-based)
        '[1, 4]'       -> ['For', 'Option D']          (ranked / approval)
        '{"1": 2, ...}'-> {'For': 2, ...}              (weighted)
    A number outside the choice list is kept as it is.

    Parameters (where they come from):
        choice_json - votes.choice_json (stored by features/votes/fetch.py).
        choices     - json.loads(proposals.choices_json), the proposal's options.
    """
    if not choice_json:
        return None
    raw = json.loads(choice_json)

    def name(number):
        i = int(number) if str(number).isdigit() else None
        return choices[i - 1] if i and 0 < i <= len(choices) else number

    if isinstance(raw, list):
        return [name(n) for n in raw]
    if isinstance(raw, dict):
        return {name(k): weight for k, weight in raw.items()}
    return name(raw)


def choice_text(decoded) -> str | None:
    """
    decode_choice() output as short text for an LLM prompt:
    'For' / 'For, Option D' / 'For: 2, Against: 1'.

    Parameter (where it comes from):
        decoded - the return value of decode_choice(); features/chat/context.py
                  calls this when it labels a forum post with the author's vote.
    """
    if decoded is None:
        return None
    if isinstance(decoded, list):
        return ", ".join(str(x) for x in decoded)
    if isinstance(decoded, dict):
        return ", ".join(f"{k}: {v}" for k, v in decoded.items())
    return str(decoded)


def top_voter_share(conn, proposal_id: str, top_n: int = 4) -> dict | None:
    """
    How concentrated a proposal's voting power is: the largest `top_n` wallets
    and their combined share of all voting power.

    Parameters (where they come from):
        conn        - SQLite connection opened by the caller.
        proposal_id - from the URL (GET /proposals/{id}/concentration) or a chunk's metadata (chat).
        top_n       - ?top_n= query parameter (default 4), or 4 from the chat.

    Returns None if the proposal does not exist, otherwise:
        {"title", "stored_votes", "expected_votes", "partial", "total_voting_power",
         "top_n_power", "top_n_share_pct", "top_voters": [{voter, voting_power,
         power_share_pct, choice}]}
    `partial` uses the same completeness rule as the vote fetcher
    (features/votes/completeness.py). With partial data the share is measured
    against Snapshot's full tally (scores_total), so it is never inflated.
    """
    p = conn.execute(
        "SELECT title, choices_json, votes_count, scores_total FROM proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()
    if not p:
        return None

    votes = conn.execute(
        "SELECT voter, vp, choice_json FROM votes WHERE proposal_id = ? ORDER BY vp DESC",
        (proposal_id,),
    ).fetchall()
    choices = json.loads(p["choices_json"]) if p["choices_json"] else []
    partial = vote_status(p["votes_count"], len(votes)) == PARTIAL
    stored_power = sum(v["vp"] or 0 for v in votes)
    total_power = (p["scores_total"] or stored_power) if partial else stored_power
    top = votes[:top_n]
    top_power = sum(v["vp"] or 0 for v in top)

    def share(power):
        return round(100 * power / total_power, 2) if total_power else 0.0

    return {
        "title": p["title"],
        "stored_votes": len(votes),
        "expected_votes": p["votes_count"] or 0,
        "partial": partial,
        "total_voting_power": round(total_power, 2),
        "top_n_power": round(top_power, 2),
        "top_n_share_pct": round(100 * top_power / total_power, 1) if total_power else 0.0,
        "top_voters": [
            {"voter": v["voter"], "voting_power": round(v["vp"] or 0, 4),
             "power_share_pct": share(v["vp"] or 0),
             "choice": decode_choice(v["choice_json"], choices)}
            for v in top
        ],
    }


# ── Where control goes next ───────────────────────────────────────────────────
# This file only calculates; control returns to whichever module called it:
#   features/daos/service.py      -> features/daos/routes.py      (GET /daos, /daos/{id})
#   features/proposals/service.py -> features/proposals/routes.py (GET /proposals...)
#   features/chat/context.py      -> features/chat/prompt.py      (POST /chat prompt)
# If a proposal id is unknown: top_voter_share returns None and the caller
#   turns that into a 404 (proposals routes) or skips the facts (chat).
# If you change a formula here, every endpoint and the chat change together;
#   tests/test_metrics.py and tests/test_regression_real_db.py pin the results.
