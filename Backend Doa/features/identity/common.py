# features/identity/common.py
"""
features/identity/common.py — Shared rules for linking forum usernames to wallets.

WHAT THIS FILE DOES
    Forum posts carry a username, votes carry a wallet; nothing connects them.
    The strategies in features/identity/strategies/ each find evidence for a
    (username -> wallet) link. They all go through the helpers here, so the
    rules are the same everywhere:
      * upsert_identity        writes a link; usernames lower-case; a stronger
                               link is never replaced by a weaker one
      * confidence_for         "high" if the wallet voted in the user's DAO, else "medium"
      * normalize_usernames    one-off fix for rows stored in mixed case
      * normalize_handle       'AlexCutler.eth' / 'alexcutler_eth' -> 'alexcutler'
      * verified_ens_name      a wallet's ENS name, only if verified both ways
      * WALLET_RE / ENS_RE     what counts as a wallet address / an ENS name in text

WHERE IT SITS
    features/identity/strategies/*.py, features/identity/routes.py,
    features/chat/context.py  --> THIS FILE --> SQLite (resolved_identities, wallet_ens)

INPUTS
    conn - an open SQLite connection passed in by the caller.
"""

import re
from datetime import datetime, timezone

CONFIDENCE_RANK = {"unresolved": 0, "low": 1, "medium": 2, "high": 3, "certain": 4}
# Exactly 40 hex characters after "0x". The look-arounds stop it from matching the
# first 40 characters of a longer value, e.g. a 64-character transaction hash.
WALLET_RE = re.compile(r"(?<![0-9a-zA-Z])0x[a-fA-F0-9]{40}(?![0-9a-zA-Z])")
ENS_RE = re.compile(r"\b([a-z0-9][a-z0-9-]{1,62}(?:\.[a-z0-9-]+)*\.eth)\b", re.IGNORECASE)


def upsert_identity(conn, username: str, wallet: str, confidence: str, method: str) -> bool:
    """
    Insert or update a link. Never replaces an equal or stronger existing confidence.
    Returns True if the table changed.

    Parameters (where they come from — every strategy in features/identity/strategies/):
        username   - a forum username (stored lower-case here).
        wallet     - the wallet the strategy found.
        confidence - one of CONFIDENCE_RANK, chosen by the strategy (often via confidence_for).
        method     - the strategy's name, e.g. "ens_username" (stored as resolution_method).
    """
    username = username.lower()
    existing = conn.execute(
        "SELECT confidence_level FROM resolved_identities WHERE forum_username = ?",
        (username,),
    ).fetchone()
    if existing and CONFIDENCE_RANK.get(existing["confidence_level"], 0) >= CONFIDENCE_RANK[confidence]:
        return False
    conn.execute(
        """
        INSERT INTO resolved_identities
            (forum_username, wallet_address, confidence_level, resolution_method, resolved_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(forum_username) DO UPDATE SET
            wallet_address=excluded.wallet_address,
            confidence_level=excluded.confidence_level,
            resolution_method=excluded.resolution_method,
            resolved_at=excluded.resolved_at
        """,
        (username, wallet, confidence, method, datetime.now(timezone.utc).isoformat()),
    )
    return True


def normalize_usernames(conn) -> int:
    """
    Lower-case any mixed-case forum_username rows (older code stored them as typed).
    If lower-casing collides with another row, the stronger link is kept.
    Returns the number of rows rewritten or merged.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py resolve_all / rescore.
    """
    rows = conn.execute(
        "SELECT * FROM resolved_identities WHERE forum_username != lower(forum_username)"
    ).fetchall()
    changed = 0
    for r in rows:
        conn.execute("DELETE FROM resolved_identities WHERE forum_username = ?", (r["forum_username"],))
        upsert_identity(conn, r["forum_username"], r["wallet_address"],
                        r["confidence_level"], r["resolution_method"])
        changed += 1
    conn.commit()
    return changed


def normalize_handle(s: str) -> str:
    """
    'alexcutlerdoteth', 'AlexCutler.eth', 'alexcutler_eth' -> 'alexcutler'.

    Parameter (where it comes from):
        s - an ENS name or a forum username, from strategies/voter_ens.py link_voter_ens.
    """
    s = s.lower()
    s = re.sub(r"(\.eth|_eth|-eth|doteth)$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def wallet_voted_in_user_spaces(conn, username: str, wallet: str) -> bool:
    """
    True if `wallet` voted in a DAO space where `username` posted on the forum —
    independent on-chain evidence that the link is right.

    Parameters (where they come from):
        username, wallet - a candidate link, from confidence_for() or strategies/upgrade.py.
    """
    row = conn.execute(
        """
        SELECT 1
        FROM forum_posts f
        JOIN proposals fp ON fp.id = f.proposal_id
        JOIN proposals vp ON vp.space_id = fp.space_id
        JOIN votes v ON v.proposal_id = vp.id
        WHERE lower(f.username) = ? AND lower(v.voter) = ?
        LIMIT 1
        """,
        (username.lower(), wallet.lower()),
    ).fetchone()
    return row is not None


def confidence_for(conn, username: str, wallet: str) -> str:
    """
    A name match alone is 'medium'; it is 'high' when the wallet also voted in the user's DAO.

    Parameters (where they come from):
        username, wallet - the link a strategy is about to write (ens_username,
                           voter_ens, profile).
    """
    return "high" if wallet_voted_in_user_spaces(conn, username, wallet) else "medium"


def verified_ens_name(conn, wallet: str) -> str | None:
    """
    The wallet's ENS name from the wallet_ens cache, only if it was verified both
    ways (reverse and forward lookup agree), else None.

    Parameters (where they come from):
        conn   - opened by the caller (identity routes, or run_chat for the chat).
        wallet - a linked wallet (resolved_identities.wallet_address).
    The cache is filled by strategies/voter_ens.py cache_voter_ens.
    """
    row = conn.execute(
        "SELECT ens_name FROM wallet_ens WHERE lower(wallet_address) = ? AND verified = 1", (wallet.lower(),)
    ).fetchone()
    return row["ens_name"] if row else None


# ── Where control goes next ───────────────────────────────────────────────────
# These helpers return to the strategy / route that called them. The strategies
# are run in order by features/identity/runner.py resolve_all().
# If a stronger link already exists: upsert_identity returns False and changes nothing.
