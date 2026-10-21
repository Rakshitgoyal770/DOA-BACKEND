# features/identity/strategies/registry.py
"""Manually verified delegate identities - hand-confirmed via public sources (certain)."""

from features.identity.common import upsert_identity

KNOWN_DELEGATES = {
    "entropy": "0xb4c064f466931B8d0F637654c916E3F203c46f13",
    # add more as you verify them
}


def link_registry(conn) -> dict:
    linked = sum(upsert_identity(conn, username, wallet, "certain", "registry")
                 for username, wallet in KNOWN_DELEGATES.items())
    conn.commit()
    return {"strategy": "registry", "linked": linked}
