# ingestion/ingest_forum.py
from datetime import datetime, timezone

from ingestion.discourse_client import fetch_thread, extract_posts
from db.schema import get_connection


def ingest_forum_for_proposal(proposal_id: str, discussion_url: str, conn):
    try:
        thread_json = fetch_thread(discussion_url)
    except Exception as e:
        print(f"    SKIP (fetch failed): {e}")
        return 0

    posts = extract_posts(thread_json)
    now = datetime.now(timezone.utc).isoformat()

    for post in posts:
        conn.execute(
            """
            INSERT INTO forum_posts
                (id, proposal_id, topic_id, post_number, username, content, created_at, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                content=excluded.content,
                fetched_at=excluded.fetched_at
            """,
            (post["id"], proposal_id, post["topic_id"], post["post_number"],
             post["username"], post["content"], post["created_at"], now),
        )

    conn.commit()
    print(f"    {len(posts)} forum posts ingested for proposal {proposal_id}")
    return len(posts)


def ingest_forum_for_all_linked_proposals(conn):
    proposals = conn.execute(
        "SELECT id, title, discussion_url FROM proposals WHERE discussion_url IS NOT NULL"
    ).fetchall()

    print(f"Found {len(proposals)} proposals with linked forum threads")
    total = 0
    for p in proposals:
        print(f"  {p['title'][:50]}")
        total += ingest_forum_for_proposal(p["id"], p["discussion_url"], conn)

    print(f"Total forum posts ingested: {total}")


if __name__ == "__main__":
    conn = get_connection()
    ingest_forum_for_all_linked_proposals(conn)
    conn.close()