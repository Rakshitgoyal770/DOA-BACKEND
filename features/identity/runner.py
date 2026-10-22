# features/identity/runner.py
"""
features/identity/runner.py — Runs the identity-linking strategies, and the identity command line.

WHAT THIS FILE DOES
    Links forum usernames to voting wallets by running every strategy in
    features/identity/strategies/, strongest evidence first. Because
    upsert_identity never replaces a stronger link, running the weaker
    strategies afterwards cannot spoil the strong ones.
        registry        hand-verified list                  -> certain
        ens_username    username is an ENS name             -> medium / high
        voter_ens       a voter's verified ENS = username   -> medium / high
        profile         wallet / ENS in the forum profile   -> medium / high
        self_disclosed  "my wallet is 0x..." in a post      -> low
        upgrade         raise links whose wallet voted in the user's DAO -> high

COMMAND LINE
    python -m features.identity.runner --all [--voters 300] [--limit 100]   # network: minutes
    python -m features.identity.runner --upgrade     # offline, seconds: after new votes / posts
    python -m features.identity.runner --stats       # coverage numbers only

WHERE IT SITS
    the command line above            --+
    POST /identities/resolve (routes) --+--> THIS FILE --> strategies/*.py --> SQLite
    Run it after a data sync (features/sync/runner.py) and before the index sync
    (vector/embedding.py), which copies the links into the search metadata.
"""

import argparse

from db.schema import get_connection
from features.identity.common import normalize_usernames
from features.identity.stats import identity_stats
from features.identity.strategies.ens_username import link_ens_usernames
from features.identity.strategies.profile import link_from_profiles
from features.identity.strategies.registry import link_registry
from features.identity.strategies.self_disclosed import link_self_disclosed
from features.identity.strategies.upgrade import upgrade_medium_links, upgrade_self_disclosed
from features.identity.strategies.voter_ens import cache_voter_ens, link_voter_ens


def resolve_all(conn, profile_limit: int = 100, voter_wallets: int = 300) -> dict:
    """
    Every strategy, in the order above. Returns {"usernames_normalized", "steps", "stats"}.

    Parameters (where they come from):
        conn          - opened by the CLI below or _run_resolution() in features/identity/routes.py.
        profile_limit - CLI --limit / ?profile_limit=: forum profiles to scan (network).
        voter_wallets - CLI --voters / ?voter_wallets=: top voter wallets to reverse-resolve (network).
    """
    normalized = normalize_usernames(conn)
    steps = [
        link_registry(conn),
        link_ens_usernames(conn),
        cache_voter_ens(conn, top_wallets=voter_wallets),
        link_voter_ens(conn),
        link_from_profiles(conn, limit=profile_limit),
        link_self_disclosed(conn),
        upgrade_self_disclosed(conn),
        upgrade_medium_links(conn),
    ]
    return {"usernames_normalized": normalized, "steps": steps, "stats": identity_stats(conn)}


def rescore(conn) -> dict:
    """
    The offline part only: re-check self-disclosed links, then promote links using
    the votes now stored. Takes seconds, so run it after every data sync.

    Parameter (where it comes from):
        conn - opened by the --upgrade CLI branch below.
    """
    return {"usernames_normalized": normalize_usernames(conn),
            "steps": [link_self_disclosed(conn), upgrade_self_disclosed(conn), upgrade_medium_links(conn)],
            "stats": identity_stats(conn)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Link forum usernames to wallets")
    parser.add_argument("--all", action="store_true", help="Run every strategy (network calls)")
    parser.add_argument("--upgrade", action="store_true", help="Offline only: re-check self-disclosed links and re-score against loaded votes")
    parser.add_argument("--stats", action="store_true", help="Print coverage stats")
    parser.add_argument("--limit", type=int, default=100, help="Profiles to fetch (default 100)")
    parser.add_argument("--voters", type=int, default=300, help="Top voter wallets to reverse-resolve (default 300)")
    args = parser.parse_args()

    conn = get_connection()
    if args.all:
        print(resolve_all(conn, args.limit, args.voters))
    elif args.upgrade:
        print(rescore(conn))
    else:
        print(identity_stats(conn))
    conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# From the command line: the result is printed and the program ends.
# From POST /identities/resolve: the result is stored for GET /identities/resolve/status.
# Recommended next step: python -m vector.embedding (copies the new links into the
#   search index metadata). The chat already sees new links immediately.
