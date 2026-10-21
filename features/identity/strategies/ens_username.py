# features/identity/strategies/ens_username.py
"""The forum username is itself an ENS name (e.g. 'slobo.eth'): forward-resolve it to a wallet."""

import time

from clients.ens import resolve_ens_name
from features.identity.common import confidence_for, upsert_identity


def link_ens_usernames(conn, delay: float = 0.2) -> dict:
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
