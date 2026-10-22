# features/identity/strategies/self_disclosed.py
"""
features/identity/strategies/self_disclosed.py — A wallet the author says, in their own post, is theirs.

Most addresses in forum posts are NOT the author's voting wallet. When we
checked our data they were mostly grant payout addresses ("L2 recipient
address: 0x..."), contract addresses, price feeds and multisigs. So an address
is accepted only when the words right before it claim it as the author's own:

    "my delegate address: 0x..."      "my wallet is 0x..."
    "Delegate address: 0x..."         "snapshot.org/#/profile/0x..."

Rules:
  * look at the ~60 characters just before each address
  * reject it if those characters also mention a recipient, payout, contract,
    multisig, safe or treasury
  * skip a user whose posts claim two different addresses (we can't tell which)
  * links are 'low' confidence; upgrade.py raises them to 'high' when the
    wallet actually voted in the user's DAO
  * each run recomputes everything and removes self_disclosed links that no
    longer pass, so tightening a rule also cleans up old data

WHERE IT SITS
    features/identity/runner.py resolve_all() and rescore() (--upgrade)
        --> THIS FILE --> common.upsert_identity    (no network)
"""

import re

from features.identity.common import WALLET_RE, upsert_identity

CONTEXT_CHARS = 60

# Words that claim ownership, directly followed by the address
# (allowing an optional "is" and punctuation such as ":", "=", "`", "*").
OWNERSHIP_CUE = re.compile(
    r"(?:\bmy\s+(?:[a-z]+\s+){0,2}(?:address|wallet)"          # my wallet / my voting address
    r"|\b(?:delegate|voting)\s+(?:address|wallet)"              # Delegate address: 0x...
    r"|snapshot\.[a-z]+/(?:#/)?profile/)"                       # Snapshot profile link
    r"(?:\s+is)?[\s:=\-`*()>]*$",
    re.IGNORECASE,
)

# Words that mean the address belongs to something other than the author's vote.
NOT_PERSONAL = re.compile(r"recipient|payout|contract|multisig|\bsafe\b|treasury", re.IGNORECASE)


def claimed_addresses(text: str) -> list[str]:
    """
    Addresses in `text` that the author claims as their own.

    Parameter (where it comes from):
        text - one forum post's content, from find_self_disclosed below.
    """
    found = []
    for m in WALLET_RE.finditer(text):
        before = text[max(0, m.start() - CONTEXT_CHARS):m.start()]
        if OWNERSHIP_CUE.search(before) and not NOT_PERSONAL.search(before):
            found.append(m.group())
    return found


def find_self_disclosed(conn) -> dict[str, str]:
    """
    {username: wallet} for users who claim exactly one address across their posts.

    Parameter (where it comes from):
        conn - passed down from link_self_disclosed.
    """
    claims: dict[str, dict[str, str]] = {}   # username -> {lower-case wallet: wallet as written}
    for post in conn.execute("SELECT lower(username) AS username, content FROM forum_posts"):
        for wallet in claimed_addresses(post["content"] or ""):
            claims.setdefault(post["username"], {})[wallet.lower()] = wallet
    return {user: next(iter(wallets.values()))
            for user, wallets in claims.items() if len(wallets) == 1}


def link_self_disclosed(conn) -> dict:
    """
    Remove self_disclosed links the rules no longer support, then add the valid ones.
    Returns {"strategy", "candidates", "linked", "removed"}.

    Parameter (where it comes from):
        conn - passed by features/identity/runner.py resolve_all() / rescore().
    """
    valid = find_self_disclosed(conn)

    # 1. Remove old self_disclosed links that the current rules no longer support.
    removed = 0
    existing = conn.execute(
        "SELECT forum_username, wallet_address FROM resolved_identities "
        "WHERE resolution_method = 'self_disclosed'"
    ).fetchall()
    for row in existing:
        wallet = valid.get(row["forum_username"])
        if wallet is None or wallet.lower() != row["wallet_address"].lower():
            conn.execute(
                "DELETE FROM resolved_identities "
                "WHERE forum_username = ? AND resolution_method = 'self_disclosed'",
                (row["forum_username"],),
            )
            removed += 1

    # 2. Add the links that pass. upsert_identity never weakens a stronger link.
    linked = sum(upsert_identity(conn, user, wallet, "low", "self_disclosed")
                 for user, wallet in valid.items())
    conn.commit()
    return {"strategy": "self_disclosed", "candidates": len(valid), "linked": linked, "removed": removed}


# ── Where control goes next ───────────────────────────────────────────────────
# Back to features/identity/runner.py, which runs strategies/upgrade.py next: a low
#   self-disclosed link becomes "high" if that wallet voted in the user's DAO.
