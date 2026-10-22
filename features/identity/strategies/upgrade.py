# features/identity/strategies/upgrade.py
"""
features/identity/strategies/upgrade.py — Raise links to "high" when the wallet's votes confirm them.

WHAT THIS FILE DOES
    A link found by name or text is only a guess until the chain agrees: if
    the linked wallet actually voted in a DAO where that user posts, the link
    is promoted to "high". Run it again whenever new votes are loaded.

WHERE IT SITS
    features/identity/runner.py resolve_all() and rescore() (--upgrade)
        --> THIS FILE --> common.wallet_voted_in_user_spaces   (no network)
"""

from datetime import datetime, timezone

from features.identity.common import wallet_voted_in_user_spaces


def upgrade_self_disclosed(conn) -> dict:
    """
    Self-disclosed links (low/medium) whose wallet voted in the user's DAO -> high.
    Returns how many rows actually changed.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py.
    """
    rows = conn.execute(
        "SELECT forum_username, wallet_address FROM resolved_identities WHERE resolution_method = 'self_disclosed'"
    ).fetchall()
    upgraded = 0
    for r in rows:
        if wallet_voted_in_user_spaces(conn, r["forum_username"], r["wallet_address"]):
            cur = conn.execute(
                "UPDATE resolved_identities SET confidence_level = 'high', resolved_at = ? "
                "WHERE forum_username = ? AND confidence_level IN ('low', 'medium')",
                (datetime.now(timezone.utc).isoformat(), r["forum_username"]),
            )
            upgraded += cur.rowcount      # 0 when the link was already high
    conn.commit()
    return {"strategy": "upgrade_self_disclosed", "upgraded": upgraded}


def upgrade_medium_links(conn) -> dict:
    """
    Medium links (from any method) whose wallet voted in the user's DAO -> high.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py.
    """
    rows = conn.execute(
        "SELECT forum_username, wallet_address FROM resolved_identities WHERE confidence_level = 'medium'"
    ).fetchall()
    upgraded = 0
    for r in rows:
        if wallet_voted_in_user_spaces(conn, r["forum_username"], r["wallet_address"]):
            cur = conn.execute(
                "UPDATE resolved_identities SET confidence_level = 'high' WHERE forum_username = ?",
                (r["forum_username"],),
            )
            upgraded += cur.rowcount
    conn.commit()
    return {"strategy": "upgrade_medium_links", "upgraded": upgraded}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to features/identity/runner.py, which ends the run with identity_stats()
#   (features/identity/stats.py).
