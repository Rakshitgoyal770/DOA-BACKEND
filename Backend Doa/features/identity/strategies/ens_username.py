# features/identity/strategies/ens_username.py
"""
features/identity/strategies/ens_username.py — The username IS an ENS name (e.g. 'slobo.eth').

WHAT THIS FILE DOES
    About 1 in 10 forum users chose their ENS name as their username. ENS
    resolves such a name to exactly one wallet, so this is strong evidence:
    "medium", or "high" when that wallet also voted in the user's DAO.

WHERE IT SITS
    features/identity/runner.py resolve_all() --> THIS FILE
        --> clients/ens.py resolve_ens_name (network) --> common.upsert_identity
"""

import time

from clients.ens import resolve_ens_name
from features.identity.common import confidence_for, upsert_identity


def link_ens_usernames(conn, delay: float = 0.2) -> dict:
    """
    Resolve every '*.eth' forum username and link it to the wallet it points to.

    Parameters (where they come from):
        conn  - passed by features/identity/runner.py resolve_all().
        delay - pause between ENS requests (default 0.2 s), to be polite to the API.
    Note: every run re-checks all such usernames (about 45 requests).
    """
    names = [r[0] for r in conn.execute(
        "SELECT DISTINCT username FROM forum_posts WHERE lower(username) LIKE '%.eth'"
    )]
    checked = linked = 0
    for name in names:
        wallet = resolve_ens_name(name.lower())
        time.sleep(delay)
        checked += 1
        if wallet and upsert_identity(conn, name, wallet, confidence_for(conn, name, wallet), "ens_username"):
            linked += 1
    conn.commit()
    return {"strategy": "ens_username", "checked": checked, "linked": linked}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to features/identity/runner.py resolve_all(), which runs strategies/voter_ens.py next.
# If the ENS API is down: resolve_ens_name returns None and no link is made this run.
