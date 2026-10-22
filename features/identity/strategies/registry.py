# features/identity/strategies/registry.py
"""
features/identity/strategies/registry.py — Hand-verified forum user -> wallet links ("certain").

WHAT THIS FILE DOES
    KNOWN_DELEGATES holds links a person confirmed from public sources (a
    delegate's own statement, a Tally profile, ...). They are written first and,
    being "certain", can never be replaced by an automatic strategy.
    To add one: append "forum_username": "0xwallet" below, then run
    python -m features.identity.runner --all

WHERE IT SITS
    features/identity/runner.py resolve_all() --> THIS FILE --> common.upsert_identity
"""

from features.identity.common import upsert_identity

KNOWN_DELEGATES = {
    "entropy": "0xb4c064f466931B8d0F637654c916E3F203c46f13",
    # add more as you verify them
}


def link_registry(conn) -> dict:
    """
    Write every KNOWN_DELEGATES entry as a "certain" link.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py resolve_all().
    """
    linked = sum(upsert_identity(conn, username, wallet, "certain", "registry")
                 for username, wallet in KNOWN_DELEGATES.items())
    conn.commit()
    return {"strategy": "registry", "linked": linked}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to features/identity/runner.py resolve_all(), which runs strategies/ens_username.py next.
