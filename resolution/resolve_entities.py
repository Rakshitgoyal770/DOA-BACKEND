import re
import time
from datetime import datetime, timezone

from db.schema import get_connection
from ingestion.snapshot_client import get_votes
from resolution.ens_client import get_ens_name

WALLET_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}")


def resolve_self_disclosed(conn):
    posts = conn.execute("SELECT username, content FROM forum_posts").fetchall()
    now = datetime.now(timezone.utc).isoformat()

    resolved_count = 0
    for post in posts:
        match = WALLET_PATTERN.search(post["content"])
        if match:
            wallet = match.group()
            conn.execute(
                """
                INSERT INTO resolved_identities
                    (forum_username, wallet_address, confidence_level, resolution_method, resolved_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(forum_username) DO UPDATE SET
                    wallet_address=excluded.wallet_address,
                    confidence_level=excluded.confidence_level,
                    resolution_method=excluded.resolution_method,
                    resolved_at=excluded.resolved_at
                """,
                (post["username"], wallet, "low", "self_disclosed", now),
            )
            resolved_count += 1

    conn.commit()
    print(f"Self-disclosed wallets resolved: {resolved_count}")


def resolve_via_ens(proposal_id: str, conn, limit: int = 10):
    votes = get_votes(proposal_id, first=1000)[:limit]   # only test the first `limit` voters
    posts = conn.execute(
        "SELECT DISTINCT username FROM forum_posts WHERE proposal_id = ?",
        (proposal_id,)
    ).fetchall()
    forum_usernames = [p["username"].lower() for p in posts]

    now = datetime.now(timezone.utc).isoformat()
    resolved_count = 0

    for vote in votes:
        wallet = vote["voter"]
        ens_name = get_ens_name(wallet)
        time.sleep(0.2)  # be polite to the free API

        if ens_name:
            ens_prefix = ens_name.replace(".eth", "").lower()
            if ens_prefix in forum_usernames:
                conn.execute(
                    """
                    INSERT INTO resolved_identities
                        (forum_username, wallet_address, confidence_level, resolution_method, resolved_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(forum_username) DO UPDATE SET
                        wallet_address=excluded.wallet_address,
                        confidence_level=excluded.confidence_level,
                        resolution_method=excluded.resolution_method,
                        resolved_at=excluded.resolved_at
                    """,
                    (ens_prefix, wallet, "medium", "ens", now),
                )
                resolved_count += 1

    conn.commit()
    print(f"ENS-resolved identities: {resolved_count}")
# add to resolution/resolve_entities.py

# Manually verified delegate identities — hand-confirmed via public sources
# (Tally proposals, forum posts), not auto-resolved.
KNOWN_DELEGATES = {
    "entropy": "0xb4c064f466931B8d0F637654c916E3F203c46f13",
    # add more as you verify them
}


def resolve_via_registry(conn):
    now = datetime.now(timezone.utc).isoformat()
    resolved_count = 0

    for username, wallet in KNOWN_DELEGATES.items():
        conn.execute(
            """
            INSERT INTO resolved_identities
                (forum_username, wallet_address, confidence_level, resolution_method, resolved_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(forum_username) DO UPDATE SET
                wallet_address=excluded.wallet_address,
                confidence_level=excluded.confidence_level,
                resolution_method=excluded.resolution_method,
                resolved_at=excluded.resolved_at
            """,
            (username, wallet, "certain", "registry", now),
        )
        resolved_count += 1

    conn.commit()
    print(f"Registry-resolved identities: {resolved_count}")


if __name__ == "__main__":
    conn = get_connection()
    resolve_self_disclosed(conn)
    resolve_via_ens(
        "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
        conn,
        limit=10
    )
    resolve_via_registry(conn)
    conn.close()