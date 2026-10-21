# features/identity/strategies/upgrade.py
"""Promote weak links to 'high' once the wallet's own votes show it is active in that DAO."""

from datetime import datetime, timezone

from features.identity.common import wallet_voted_in_user_spaces


def upgrade_self_disclosed(conn) -> dict:
    """A wallet a user posted themselves that also voted in that DAO is corroborated."""
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
    """Promote 'medium' links to 'high' once the wallet's votes are loaded for that DAO."""
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
