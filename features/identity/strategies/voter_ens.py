# features/identity/strategies/voter_ens.py
"""
features/identity/strategies/voter_ens.py — Match voters' ENS names to forum usernames.

WHAT THIS FILE DOES
    Works from the voting side:
      1. cache_voter_ens  look up the ENS name of the biggest voter wallets and
                          remember it in `wallet_ens` ("verified" only if the name
                          also resolves back to the same wallet)
      2. link_voter_ens   if a verified name matches a forum username (after
                          normalize_handle: 'Zeptimus.eth' ~ 'zeptimus'), link them
    Already-cached wallets are never looked up again.

WHERE IT SITS
    features/identity/runner.py resolve_all() --> THIS FILE
        --> clients/ens.py (network) --> wallet_ens table --> common.upsert_identity
"""

import time
from datetime import datetime, timezone

import requests

from clients.ens import get_ens_name, resolve_ens_name
from features.identity.common import confidence_for, normalize_handle, upsert_identity


def cache_voter_ens(conn, top_wallets: int = 300, delay: float = 0.2) -> dict:
    """
    Reverse-resolve the highest-voting-power wallets not yet cached.
    A name is `verified` only if it resolves forward to the same wallet.

    Parameters (where they come from):
        conn        - passed by features/identity/runner.py resolve_all().
        top_wallets - resolve_all's voter_wallets (CLI --voters / ?voter_wallets=, default 300).
        delay       - pause between ENS requests.
    A network error skips that wallet WITHOUT caching it, so it is retried next run.
    """
    wallets = [r[0] for r in conn.execute(
        """
        SELECT v.voter FROM votes v
        LEFT JOIN wallet_ens w ON lower(w.wallet_address) = lower(v.voter)
        WHERE w.wallet_address IS NULL
        GROUP BY lower(v.voter) ORDER BY MAX(v.vp) DESC LIMIT ?
        """,
        (top_wallets,),
    )]
    named = verified = 0
    now = datetime.now(timezone.utc).isoformat()
    for wallet in wallets:
        try:
            name = get_ens_name(wallet)
        except requests.RequestException:
            continue
        time.sleep(delay)
        ok = 0
        if name:
            named += 1
            fwd = resolve_ens_name(name.lower())
            time.sleep(delay)
            ok = int(bool(fwd) and fwd.lower() == wallet.lower())
            verified += ok
        conn.execute(
            "INSERT OR REPLACE INTO wallet_ens VALUES (?, ?, ?, ?)",
            (wallet.lower(), name, ok, now),
        )
    conn.commit()
    return {"strategy": "cache_voter_ens", "wallets_checked": len(wallets),
            "with_ens": named, "verified": verified}


def link_voter_ens(conn) -> dict:
    """
    Match cached, verified voter ENS names to forum usernames by normalized handle.
    Skips handles shorter than 4 characters and names shared by several wallets.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py resolve_all(). No network.
    """
    ens_rows = conn.execute(
        "SELECT wallet_address, ens_name FROM wallet_ens WHERE verified = 1 AND ens_name IS NOT NULL"
    ).fetchall()
    by_handle: dict[str, list] = {}
    for r in ens_rows:
        by_handle.setdefault(normalize_handle(r["ens_name"]), []).append(r["wallet_address"])

    linked = 0
    for (username,) in conn.execute("SELECT DISTINCT lower(username) FROM forum_posts").fetchall():
        key = normalize_handle(username)
        wallets = by_handle.get(key) if len(key) >= 4 else None
        if not wallets or len(wallets) != 1:   # skip short handles and ambiguous matches
            continue
        wallet = wallets[0]
        if upsert_identity(conn, username, wallet, confidence_for(conn, username, wallet), "voter_ens"):
            linked += 1
    conn.commit()
    return {"strategy": "voter_ens", "linked": linked}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to features/identity/runner.py resolve_all(), which runs strategies/profile.py next.
# The wallet_ens cache is also read by common.verified_ens_name (ENS names shown in
#   the identity endpoints and the chat).
