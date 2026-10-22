# clients/ens.py
"""
clients/ens.py — ENS lookups in both directions (wallet <-> name) via the free ensideas API.

WHAT THIS FILE DOES
    ENS gives wallets readable names such as "slobo.eth".
      * get_ens_name      wallet -> its primary ENS name   (reverse lookup)
      * resolve_ens_name  ENS name -> the wallet it points to (forward lookup)
    A reverse name is only trustworthy if it also resolves forward to the same
    wallet; features/identity/strategies/voter_ens.py checks exactly that.

WHERE IT SITS
    features/identity/strategies/*.py --> THIS FILE --> api.ensideas.com
    (no database access here)
"""

import requests

from clients import USER_AGENT

ENS_URL = "https://api.ensideas.com/ens/resolve/{query}"
REQUEST_TIMEOUT = 10   # seconds


def _lookup(query: str) -> dict | None:
    """
    The API's JSON for a wallet or a name, or None if it has no answer (non-200).
    Network errors are raised, so callers can tell "no name" from "could not ask".

    Parameter (where it comes from):
        query - a wallet address or an ENS name, from the two functions below.
    """
    resp = requests.get(ENS_URL.format(query=query), timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": USER_AGENT})
    return resp.json() if resp.status_code == 200 else None


def get_ens_name(wallet_address: str) -> str | None:
    """
    Reverse lookup: wallet -> primary ENS name, or None if it has none.
    RAISES on network errors on purpose: the caller caches the answer, and a
    network failure must not be cached as "this wallet has no name".

    Parameter (where it comes from):
        wallet_address - a voter wallet from the votes table, chosen by
                         features/identity/strategies/voter_ens.py cache_voter_ens.
    """
    data = _lookup(wallet_address)
    return data.get("name") if data else None


def resolve_ens_name(name: str) -> str | None:
    """
    Forward lookup: 'slobo.eth' -> wallet address, or None. Never raises:
    a failed lookup simply means no link is made this time.

    Parameter (where it comes from):
        name - an ENS name from a forum username (strategies/ens_username.py),
               a Discourse profile (strategies/profile.py), or a reverse
               lookup being verified (strategies/voter_ens.py).
    """
    try:
        data = _lookup(name)
    except (requests.RequestException, ValueError):
        return None
    return data.get("address") if data else None


if __name__ == "__main__":
    # Manual check: python -m clients.ens   (vitalik.eth's known address)
    print(get_ens_name("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"))


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the identity strategy that asked, which decides whether the
# answer becomes a forum-user -> wallet link (features/identity/common.py upsert_identity).
# If the ENS API is down: get_ens_name raises (that wallet is retried next run),
#   resolve_ens_name returns None (no link this run).
