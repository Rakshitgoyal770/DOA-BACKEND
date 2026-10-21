# features/identity/common.py
"""
Shared rules for linking forum usernames to wallets.

Every strategy in `strategies/` writes through `upsert_identity`, which keeps
usernames lower-case and never replaces a stronger link with a weaker one.
"""

import re
from datetime import datetime, timezone

CONFIDENCE_RANK = {"unresolved": 0, "low": 1, "medium": 2, "high": 3, "certain": 4}
# Exactly 40 hex characters after "0x". The look-arounds stop it from matching the
# first 40 characters of a longer value, e.g. a 64-character transaction hash.
WALLET_RE = re.compile(r"(?<![0-9a-zA-Z])0x[a-fA-F0-9]{40}(?![0-9a-zA-Z])")
ENS_RE = re.compile(r"\b([a-z0-9][a-z0-9-]{1,62}(?:\.[a-z0-9-]+)*\.eth)\b", re.IGNORECASE)


def upsert_identity(conn, username: str, wallet: str, confidence: str, method: str) -> bool:
    """Insert or update a link. Never replaces an equal or stronger existing confidence.
    Returns True if the table changed."""
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
    """Lower-case any mixed-case forum_username rows (older code stored them as typed).
    If lower-casing collides with another row, the stronger link is kept.
    Returns the number of rows rewritten or merged."""
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
    """'alexcutlerdoteth', 'AlexCutler.eth', 'alexcutler_eth' -> 'alexcutler'."""
    s = s.lower()
    s = re.sub(r"(\.eth|_eth|-eth|doteth)$", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def wallet_voted_in_user_spaces(conn, username: str, wallet: str) -> bool:
    """True if `wallet` voted in a DAO space where `username` posted on the forum."""
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
    """A name match alone is 'medium'; it is 'high' when the wallet also voted in the user's DAO."""
    return "high" if wallet_voted_in_user_spaces(conn, username, wallet) else "medium"
