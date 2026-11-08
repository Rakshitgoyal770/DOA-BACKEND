# features/identity/strategies/profile.py
"""
features/identity/strategies/profile.py — Link a forum user to a wallet via their Discourse profile.

WHAT THIS FILE DOES
    Some users put a wallet address or an ENS name in their forum profile
    (name, bio, website). For the most active users that are not linked yet,
    this fetches the profile and looks for either:
        a 0x... wallet       -> method "profile_wallet"
        an ENS name (x.eth)  -> resolved to a wallet -> method "profile_ens"
    Confidence: "high" if that wallet voted in the user's DAO, else "medium"
    (features/identity/common.py confidence_for).

WHERE IT SITS
    features/identity/runner.py resolve_all() --> THIS FILE
        --> clients/discourse.py (profile), clients/ens.py (name -> wallet)
        --> features/identity/common.py upsert_identity (writes the link)
"""

import time

from clients.discourse import fetch_discourse_profile, forum_base_url
from clients.ens import resolve_ens_name
from features.identity.common import ENS_RE, WALLET_RE, confidence_for, upsert_identity


def _a_thread_of(conn, username: str) -> str | None:
    """
    The discussion URL of one thread the user posted in (tells us which forum
    their profile lives on), or None.

    Parameters (where they come from — link_from_profiles below):
        conn     - passed down.
        username - a forum username from the query in link_from_profiles.
    """
    row = conn.execute(
        """
        SELECT p.discussion_url FROM forum_posts f
        JOIN proposals p ON p.id = f.proposal_id
        WHERE lower(f.username) = ? AND p.discussion_url LIKE 'http%' LIMIT 1
        """,
        (username.lower(),),
    ).fetchone()
    return row["discussion_url"] if row else None


def link_from_profiles(conn, limit: int = 100, delay: float = 0.3) -> dict:
    """
    Fetch profiles of the `limit` most active unlinked posters and link any
    wallet or ENS name found. Returns counts per method.

    Parameters (where they come from — features/identity/runner.py resolve_all):
        conn  - opened by the identity CLI or POST /identities/resolve.
        limit - resolve_all's profile_limit (CLI --limit, API ?profile_limit=, default 100).
        delay - pause between profile requests, to be polite to the forums.
    """
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
        thread = _a_thread_of(conn, username)
        if not thread:
            continue
        profile = fetch_discourse_profile(forum_base_url(thread), username)
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


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/identity/runner.py resolve_all(), which runs the
# next strategy (strategies/self_disclosed.py).
# If a profile cannot be fetched (unknown user, blocked, network): that user is
#   skipped this run and tried again next run.
