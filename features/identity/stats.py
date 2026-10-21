# features/identity/stats.py
"""Coverage numbers for forum-user -> wallet links."""


def identity_stats(conn) -> dict:
    total_users = conn.execute("SELECT COUNT(DISTINCT lower(username)) FROM forum_posts").fetchone()[0]
    total_posts = conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0]
    by_method = {r[0]: r[1] for r in conn.execute(
        "SELECT resolution_method, COUNT(*) FROM resolved_identities GROUP BY 1")}
    by_conf = {r[0]: r[1] for r in conn.execute(
        "SELECT confidence_level, COUNT(*) FROM resolved_identities GROUP BY 1")}
    resolved = sum(by_method.values())
    medium_plus = sum(by_conf.get(k, 0) for k in ("medium", "high", "certain"))
    posts_linked = conn.execute(
        "SELECT COUNT(*) FROM forum_posts f JOIN resolved_identities r ON r.forum_username = lower(f.username)"
    ).fetchone()[0]
    posts_with_vp = conn.execute(
        """
        SELECT COUNT(*) FROM forum_posts f
        JOIN resolved_identities r ON r.forum_username = lower(f.username)
        JOIN votes v ON v.proposal_id = f.proposal_id AND lower(v.voter) = lower(r.wallet_address)
        """
    ).fetchone()[0]
    pct = lambda n, d: round(100 * n / d, 1) if d else 0.0
    return {
        "forum_users": total_users,
        "resolved": resolved,
        "coverage_pct": pct(resolved, total_users),
        "medium_plus": medium_plus,
        "medium_plus_pct": pct(medium_plus, total_users),
        "forum_posts": total_posts,
        "posts_by_linked_users": posts_linked,
        "posts_coverage_pct": pct(posts_linked, total_posts),
        "posts_with_voting_power": posts_with_vp,
        "by_method": by_method,
        "by_confidence": by_conf,
    }
