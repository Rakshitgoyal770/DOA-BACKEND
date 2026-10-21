# features/identity/runner.py
"""
Runs the identity-linking strategies, strongest evidence first, and exposes the command line.

    python -m features.identity.runner --all [--voters 400] [--limit 150]
    python -m features.identity.runner --upgrade       # offline: re-check self-disclosed links, re-score
    python -m features.identity.runner --stats
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
    """Run every strategy; stronger evidence is written first and is never overwritten by weaker."""
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
    """Cheap, offline: re-check self-disclosed links, then promote links using loaded votes."""
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
