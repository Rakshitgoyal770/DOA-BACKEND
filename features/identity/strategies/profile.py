# features/identity/strategies/profile.py
"""Scan Discourse profiles (name / bio / website) of unresolved posters for a wallet or ENS name."""

import time
from urllib.parse import urlparse

from clients.discourse import fetch_discourse_profile
from clients.ens import resolve_ens_name
from features.identity.common import ENS_RE, WALLET_RE, confidence_for, upsert_identity


def _forum_base_for(conn, username: str) -> str | None:
    row = conn.execute(
        """
        SELECT p.discussion_url FROM forum_posts f
        JOIN proposals p ON p.id = f.proposal_id
        WHERE lower(f.username) = ? AND p.discussion_url LIKE 'http%' LIMIT 1
        """,
        (username.lower(),),
    ).fetchone()
    if not row:
        return None
    u = urlparse(row["discussion_url"])
    return f"{u.scheme}://{u.netloc}"


def link_from_profiles(conn, limit: int = 100, delay: float = 0.3) -> dict:
    """Fetch profiles for the most active unresolved posters and look for a wallet/ENS."""
    users = [r[0] for r in conn.execute(
        """
        SELECT f.username FROM forum_posts f
        LEFT JOIN resolved_identities r ON r.forum_username = lower(f.username)
        WHERE r.forum_username IS NULL
        GROUP BY lower(f.username) ORDER BY COUNT(*) DESC LIMIT ?
        """,
        (limit,),
    )]
    fetched = wallet_links = ens_links = 0
    for username in users:
        base = _forum_base_for(conn, username)
        if not base:
            continue
        profile = fetch_discourse_profile(base, username)
        time.sleep(delay)
        if not profile:
            continue
        fetched += 1
        blob = " ".join(profile.values())

        m = WALLET_RE.search(blob)
        if m and upsert_identity(conn, username, m.group(), confidence_for(conn, username, m.group()),
                                 "profile_wallet"):
            wallet_links += 1
            continue
        for ens in ENS_RE.findall(blob):
            wallet = resolve_ens_name(ens.lower())
            time.sleep(0.2)
            if wallet and upsert_identity(conn, username, wallet, confidence_for(conn, username, wallet),
                                          "profile_ens"):
                ens_links += 1
                break
    conn.commit()
    return {"strategy": "profiles", "profiles_fetched": fetched,
            "profile_wallet": wallet_links, "profile_ens": ens_links}
