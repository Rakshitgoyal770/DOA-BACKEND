# features/identity/strategies/self_disclosed.py
"""A wallet address written inside the author's own forum post (weak evidence: 'low')."""

from features.identity.common import WALLET_RE, upsert_identity


def link_self_disclosed(conn) -> dict:
    posts = conn.execute("SELECT username, content FROM forum_posts").fetchall()
    linked = 0
    for post in posts:
        match = WALLET_RE.search(post["content"] or "")
        if match and upsert_identity(conn, post["username"], match.group(), "low", "self_disclosed"):
            linked += 1
    conn.commit()
    return {"strategy": "self_disclosed", "linked": linked}
