# clients/discourse.py
"""
clients/discourse.py — Reads forum threads, posts and user profiles from Discourse forums.

WHAT THIS FILE DOES
    Each DAO discusses proposals on a Discourse forum (gov.optimism.io,
    governance.aave.com, ...). A proposal on Snapshot links its thread
    (proposals.discussion_url). This file turns such a link into posts:
      * is_discourse_thread / normalize_discourse_url   recognise and clean a thread link
      * fetch_full_thread    EVERY post of a thread (see below)
      * post_record          one raw post -> the fields we store (HTML removed)
      * fetch_discourse_profile   a user's name / bio / website (for identity linking)

WHY "FULL" THREAD
    A thread's JSON (/t/<id>.json) contains only the FIRST 20 posts, plus the ids
    of every post in `post_stream.stream`. The rest must be requested by id from
    /t/<id>/posts.json, at most 20 per request. Reading only the first page is
    what used to cut 35 threads at exactly 20 posts.

WHERE IT SITS
    features/forum/fetch.py, features/forum/completeness.py,
    features/identity/strategies/profile.py  --> THIS FILE --> internet
    (no database access here)
"""

import re
import time
import urllib.parse
from html import unescape

import requests

from clients import USER_AGENT

REQUEST_TIMEOUT = 15     # seconds
POSTS_PER_REQUEST = 20   # Discourse returns at most 20 posts per request
PAUSE = 0.3              # seconds between requests, to be polite to the forum


def strip_html(cooked: str) -> str:
    """
    Plain text from Discourse's rendered HTML ("cooked"): tags removed,
    entities like &rsquo; decoded, whitespace collapsed.

    Parameter (where it comes from):
        cooked - raw_post["cooked"], via post_record().
    """
    text = re.sub(r"<[^>]+>", " ", cooked)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def is_discourse_thread(url: str | None) -> bool:
    """
    True if a proposal's discussion link points at a Discourse topic ("/t/").
    Some proposals link elsewhere (e.g. a GitHub gist); those are skipped.

    Parameter (where it comes from):
        url - proposals.discussion_url, checked by features/forum/completeness.py
              linked_threads() and by fetch_thread() below.
    """
    return bool(url) and "/t/" in url and "gist.github" not in url


def normalize_discourse_url(url: str) -> str:
    """
    The thread's JSON endpoint for any human-facing link to it:
        .../t/slug/31407?u=entropy   -> .../t/slug/31407.json
        .../t/slug/31407/42          -> .../t/slug/31407.json   (post number dropped)
        .../t/name-only-slug         -> .../t/name-only-slug.json
    Safe to call twice: a ".json" URL comes back unchanged.

    Parameter (where it comes from):
        url - proposals.discussion_url (features/forum/completeness.py groups
              proposals by this normalized URL, so one thread = one entry).
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip('/').removesuffix('.json')
    m = re.match(r'(.*?/t/(?:[^/]+/)?\d+)', path)   # keep up to the topic id
    clean_path = m.group(1) if m else path
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}.json"


def forum_base_url(url: str) -> str:
    """
    'https://gov.optimism.io/t/slug/123' -> 'https://gov.optimism.io'.

    Parameter (where it comes from):
        url - a thread URL: fetch_posts_by_id() below, and
              features/identity/strategies/profile.py (to find a user's forum).
    """
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_thread(thread_url: str) -> dict:
    """
    The thread's JSON: first 20 posts in post_stream.posts, every post id in
    post_stream.stream, and the topic id in "id".

    Parameter (where it comes from):
        thread_url - any link to the thread (fetch_full_thread passes the
                     normalized URL from features/forum/fetch.py).
    Raises ValueError for a non-Discourse link, requests.HTTPError for e.g. 404.
    """
    if not is_discourse_thread(thread_url):
        raise ValueError(f"Not a valid Discourse topic URL: {thread_url}")
    resp = requests.get(normalize_discourse_url(thread_url),
                        headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    time.sleep(PAUSE)
    return resp.json()


def fetch_posts_by_id(thread_url: str, topic_id: int, post_ids: list[int]) -> list[dict]:
    """
    Raw posts for the given ids, requested 20 at a time.

    Parameters (where they come from — all from fetch_full_thread below):
        thread_url - the thread link (only its https://host part is used).
        topic_id   - the thread JSON's "id".
        post_ids   - the listed ids we do not have yet.
    """
    posts = []
    for start in range(0, len(post_ids), POSTS_PER_REQUEST):
        batch = post_ids[start:start + POSTS_PER_REQUEST]
        resp = requests.get(
            f"{forum_base_url(thread_url)}/t/{topic_id}/posts.json",
            params=[("post_ids[]", i) for i in batch],
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        posts.extend(resp.json().get("post_stream", {}).get("posts", []))
        time.sleep(PAUSE)
    return posts


def fetch_full_thread(thread_url: str, known_ids: set[int] = frozenset()) -> dict:
    """
    Every post of a thread. Returns:
        {"topic_id": int, "listed_ids": [every id Discourse lists], "posts": [raw posts]}
    A listed id may be missing from "posts" if it was deleted or hidden meanwhile.

    Parameters (where they come from — features/forum/fetch.py fetch_forum_threads):
        thread_url - the normalized thread URL from forum_completeness().
        known_ids  - post ids already stored for every proposal linking this
                     thread; beyond the first page those are not downloaded again,
                     so re-checking an unchanged thread costs one request.
    """
    thread = fetch_thread(thread_url)
    first_page = thread.get("post_stream", {}).get("posts", [])
    listed_ids = thread.get("post_stream", {}).get("stream") or [p["id"] for p in first_page]

    have = {p["id"] for p in first_page} | set(known_ids)
    missing = [i for i in listed_ids if i not in have]
    return {
        "topic_id": thread["id"],
        "listed_ids": listed_ids,
        "posts": first_page + fetch_posts_by_id(thread_url, thread["id"], missing),
    }


def post_record(raw: dict, topic_id: int) -> dict:
    """
    One raw Discourse post as the fields we store:
    {id, topic_id, post_number, username, content, created_at}.

    Parameters (where they come from — features/forum/fetch.py):
        raw      - one item of fetch_full_thread()["posts"].
        topic_id - fetch_full_thread()["topic_id"].
    """
    return {
        "id": raw["id"],
        "topic_id": topic_id,
        "post_number": raw["post_number"],
        "username": raw["username"],
        "content": strip_html(raw.get("cooked") or ""),
        "created_at": raw["created_at"],
    }


def fetch_discourse_profile(base_url: str, username: str) -> dict | None:
    """
    A forum user's public profile: {name, bio, website, location}, or None
    (unknown user, blocked, or network error — never raises).

    Parameters (where they come from — features/identity/strategies/profile.py):
        base_url - forum_base_url() of a thread the user posted in.
        username - the Discourse username (forum_posts.username).
    """
    try:
        resp = requests.get(f"{base_url}/u/{username}.json", timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return None
        user = resp.json().get("user", {})
    except (requests.RequestException, ValueError):
        return None
    return {
        "name": user.get("name") or "",
        "bio": user.get("bio_raw") or "",
        "website": user.get("website") or "",
        "location": user.get("location") or "",
    }


if __name__ == "__main__":
    # Manual check against the live forum: python -m clients.discourse
    thread = fetch_full_thread(
        "https://forum.arbitrum.foundation/t/"
        "banning-projects-identified-in-the-high-severity-watchdog-program-cases/31407"
    )
    print("Listed posts:", len(thread["listed_ids"]), "| fetched:", len(thread["posts"]))
    for raw in thread["posts"][:5]:
        post = post_record(raw, thread["topic_id"])
        print(f"[{post['post_number']}] {post['username']}: {post['content'][:80]}...")


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller, which decides what to store:
#   features/forum/fetch.py                  fetch_full_thread, post_record -> forum_posts
#   features/forum/completeness.py           is_discourse_thread, normalize_discourse_url
#   features/identity/strategies/profile.py  fetch_discourse_profile, forum_base_url
# If a thread link is dead (HTTP 404) or the forum is down: requests raises; the
#   forum fetcher records it in forum_threads.last_error and retries next sync.
