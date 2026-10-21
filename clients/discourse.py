# clients/discourse.py
"""
Read Discourse forum threads.

A thread's JSON (/t/<id>.json) contains only the FIRST 20 posts, plus the ids
of every post in `post_stream.stream`. The rest must be requested by id from
/t/<id>/posts.json, at most 20 per request. `fetch_full_thread` does both.
"""
import re
import time
import urllib.parse
from html import unescape

import requests

USER_AGENT = "Mozilla/5.0 (compatible; DAOGovernanceResearch/0.1)"
REQUEST_TIMEOUT = 15     # seconds
POSTS_PER_REQUEST = 20   # Discourse returns at most 20 posts per request
PAUSE = 0.3              # seconds between requests, to be polite to the forum


def strip_html(cooked: str) -> str:
    text = re.sub(r"<[^>]+>", " ", cooked)   # remove HTML tags
    text = unescape(text)                     # convert entities like &rsquo; back to normal chars
    text = re.sub(r"\s+", " ", text).strip()  # collapse whitespace into single spaces
    return text


def normalize_discourse_url(url: str) -> str:
    """
    Normalizes human-facing Discourse URLs to the JSON endpoint:
    Strips query parameters (?u=...), trailing slashes, and post numbers (/20526/42 -> /20526).
    Safe to call twice: an already-normalized ".json" URL comes back unchanged.
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip('/').removesuffix('.json')
    # If path has a sub-post number like /t/slug/12345/42, extract up to the topic id
    m = re.match(r'(.*?/t/(?:[^/]+/)?\d+)', path)
    if m:
        clean_path = m.group(1)
    else:
        clean_path = path
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}.json"


def fetch_thread(thread_url: str) -> dict:
    """
    thread_url: the human-facing URL, e.g.
    https://forum.arbitrum.foundation/t/some-slug/31407?u=entropy
    Normalized and appended with .json for Discourse's structured API.
    """
    # Skip non-discourse or raw gist files
    if "gist.github" in thread_url or not ("/t/" in thread_url):
        raise ValueError(f"Not a valid Discourse topic URL: {thread_url}")

    json_url = normalize_discourse_url(thread_url)
    headers = {"User-Agent": USER_AGENT}

    resp = requests.get(json_url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    time.sleep(PAUSE)

    return resp.json()


def forum_base_url(thread_url: str) -> str:
    """'https://gov.optimism.io/t/slug/123' -> 'https://gov.optimism.io'."""
    parsed = urllib.parse.urlparse(thread_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_posts_by_id(thread_url: str, topic_id: int, post_ids: list[int]) -> list[dict]:
    """Raw posts for the given ids, requested 20 at a time."""
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
    Every post of a thread, skipping ids in `known_ids` (posts we already have)
    beyond the first page. Returns:
        {"topic_id": int, "listed_ids": [every id Discourse lists], "posts": [raw posts]}
    A listed id may be missing from "posts" if it was deleted or hidden meanwhile.
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
    """One raw Discourse post as {id, topic_id, post_number, username, content, created_at}."""
    return {
        "id": raw["id"],
        "topic_id": topic_id,
        "post_number": raw["post_number"],
        "username": raw["username"],
        "content": strip_html(raw.get("cooked") or ""),
        "created_at": raw["created_at"],
    }


def fetch_discourse_profile(base_url: str, username: str) -> dict | None:
    """Returns {name, bio, website, location} from /u/{username}.json, or None."""
    try:
        resp = requests.get(f"{base_url}/u/{username}.json", timeout=10,
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
    # Test 1 — strip_html on known text
    test_html = '<p>Voting FOR. Sad to read proposals like this one.</p>'
    print(strip_html(test_html))
    print()

    # Test 2 — fetch a real thread, all pages
    thread = fetch_full_thread(
        "https://forum.arbitrum.foundation/t/"
        "banning-projects-identified-in-the-high-severity-watchdog-program-cases/31407"
    )
    print("Listed posts:", len(thread["listed_ids"]), "| fetched:", len(thread["posts"]))
    for raw in thread["posts"][:5]:
        post = post_record(raw, thread["topic_id"])
        print(f"[{post['post_number']}] {post['username']}: {post['content'][:80]}...")