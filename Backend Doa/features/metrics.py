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
      * proposal status    whether voting is open RIGHT NOW (upcoming / open / ended_unsettled /
                           closed), from the voting dates and the clock, not the stored label alone

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
import time
from datetime import datetime, timezone

from features.votes.completeness import PARTIAL, vote_status

# SQL fragment for "number of different forum posters", used inside the
# proposal queries of features/daos/service.py and features/proposals/service.py
# (they join forum_posts as `fp`). Usernames are compared lower-case, so
# "Alice" and "alice" are one person.
FORUM_POSTERS_SQL = "COUNT(DISTINCT lower(fp.username))"


# ── Is a proposal open for voting? ────────────────────────────────────────────

# What each status means, in the words the chat may repeat. Returned by the chat lookups
# next to every status so the writer never has to guess what a label means.
STATUS_MEANS = {
    "upcoming": "voting has not opened yet",
    "open": "voting is open now",
    "ended_unsettled": "voting has ended, but the final result is not confirmed in our data yet",
    "closed": "voting has ended and the result is final",
    "unknown": "we have no dates or state for this proposal",
}

# Where a proposal is in its life: 0 = before voting, 1 = voting open, 2 = voting over.
_STAGE_OF_STATE = {"pending": 0, "active": 1, "closed": 2}
_STATUS_OF_STAGE = {0: "upcoming", 1: "open"}


def utc_now() -> int:
    """Now, as UTC epoch seconds. A function (not time.time() inline) so tests can freeze the clock."""
    return int(time.time())


def _field(row, key):
    """row[key] for a sqlite3.Row or a dict; None when the column is not there."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _epoch(iso: str | None) -> int | None:
    """'2026-10-22T09:36:29.455707+00:00' -> UTC epoch seconds, or None if missing or unreadable."""
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp())


def proposal_status(row, now: int | None = None) -> dict:
    """
    Whether a proposal is open for voting RIGHT NOW. Returns:
        status          upcoming | open | ended_unsettled | closed | unknown  (see STATUS_MEANS)
        stored_state    the label Snapshot gave it at our last sync (pending | active | closed)
        stale_label     True when the label is behind the clock, e.g. stored 'active' but the voting
                        window is over (our data is older than the vote)
        voting_ends     end time, UTC epoch seconds (None if unknown)
        seconds_left    while open: seconds until voting ends, else None
        data_age_seconds  how old our copy of the proposal is (None if fetched_at is missing)

    THE RULE
      The stored label only changes when we sync, so it can fall BEHIND reality but never ahead of
      it. The voting window (start_ts, end_ts) is checked against the clock, so it is always current.
      The proposal is in whichever stage is FURTHER ALONG: a label of 'active' cannot keep a
      proposal open after end_ts, and a label of 'closed' is believed even if the clock disagrees.
      Once voting is over it is 'closed' only if Snapshot's scores are final (scores_state 'final';
      an older row with no scores_state and the label 'closed' also counts), else 'ended_unsettled'.

    Parameters (where they come from):
        row - a proposals row (sqlite3.Row or dict) with state, start_ts, end_ts and, when known,
              scores_state and fetched_at. Missing columns count as unknown.
        now - UTC epoch seconds; None = the current time. Tests pass a fixed value.
    """
    now = utc_now() if now is None else int(now)
    start, end = _field(row, "start_ts"), _field(row, "end_ts")
    label, scores_state = _field(row, "state"), _field(row, "scores_state")

    by_clock = None if start is None or end is None else (0 if now < start else 1 if now < end else 2)
    by_label = _STAGE_OF_STATE.get(label)
    stages = [s for s in (by_clock, by_label) if s is not None]

    if not stages:
        status = "unknown"
    elif max(stages) < 2:
        status = _STATUS_OF_STAGE[max(stages)]
    elif scores_state == "final" or (scores_state is None and label == "closed"):
        status = "closed"
    else:
        status = "ended_unsettled"

    fetched = _epoch(_field(row, "fetched_at"))
    return {
        "status": status,
        "stored_state": label,
        "stale_label": by_clock is not None and by_label is not None and by_clock > by_label,
        "voting_ends": end,
        "seconds_left": (end - now) if status == "open" and end is not None else None,
        "data_age_seconds": max(0, now - fetched) if fetched is not None else None,
    }


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


def winning_choice(choices_json: str | None, scores_json: str | None) -> str | None:
    """
    The name of the choice with the most voting power, or None.

    Parameters (where they come from):
        choices_json - proposals.choices_json, e.g. '["For", "Against"]'.
        scores_json  - proposals.scores_json, voting power per choice in the same order.
    """
    if not choices_json or not scores_json:
        return None
    choices, scores = json.loads(choices_json), json.loads(scores_json)
    if not choices or not scores:
        return None
    return choices[max(range(min(len(choices), len(scores))), key=lambda i: scores[i])]


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
