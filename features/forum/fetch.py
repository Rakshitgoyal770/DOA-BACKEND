# features/forum/fetch.py
"""Pull Discourse thread posts for proposals that link to a forum discussion."""

import datetime
import logging

from clients.discourse import extract_posts, fetch_thread

logger = logging.getLogger(__name__)


def fetch_missing_forum_posts(conn, limit: int = 20) -> int:
    """
    Fetches forum discussion posts for proposals that have a discussion_url
    but zero posts in the database.
    """
    missing_props = conn.execute("""
        SELECT p.id, p.title, p.discussion_url
        FROM proposals p
        LEFT JOIN forum_posts f ON p.id = f.proposal_id
        WHERE p.discussion_url IS NOT NULL 
          AND p.discussion_url != ''
          AND f.id IS NULL
        LIMIT ?
    """, (limit,)).fetchall()

    logger.info(f"Found {len(missing_props)} proposals needing forum posts...")
    total_posts_added = 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for p in missing_props:
        url = p["discussion_url"]
        try:
            thread_data = fetch_thread(url)
            posts = extract_posts(thread_data)
            for post in posts:
                conn.execute("""
                    INSERT INTO forum_posts
                        (id, proposal_id, topic_id, post_number, username, content, created_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        content = excluded.content,
                        fetched_at = excluded.fetched_at
                """, (
                    post["id"], p["id"], post["topic_id"], post["post_number"],
                    post["username"], post["content"], post["created_at"], now
                ))
            conn.commit()
            total_posts_added += len(posts)
            logger.info(f"  + {len(posts)} posts ingested for '{p['title'][:40]}'")
        except Exception as e:
            logger.warning(f"  Skip '{p['title'][:35]}': {e}")

    return total_posts_added
