# ingestion/discourse_client.py
import re
import time
import requests
from html import unescape

USER_AGENT = "Mozilla/5.0 (compatible; DAOGovernanceResearch/0.1)"


def strip_html(cooked: str) -> str:
    text = re.sub(r"<[^>]+>", " ", cooked)   # remove HTML tags
    text = unescape(text)                     # convert entities like &rsquo; back to normal chars
    text = re.sub(r"\s+", " ", text).strip()  # collapse whitespace into single spaces
    return text


import urllib.parse

def normalize_discourse_url(url: str) -> str:
    """
    Normalizes human-facing Discourse URLs to the JSON endpoint:
    Strips query parameters (?u=...), trailing slashes, and post numbers (/20526/42 -> /20526)
    """
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip('/')
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

    resp = requests.get(json_url, headers=headers, timeout=10)
    resp.raise_for_status()
    time.sleep(0.3)  # be polite, don't hammer the forum

    return resp.json()


def extract_posts(thread_json: dict) -> list[dict]:
    """Returns a flat list of {id, topic_id, post_number, username, content, created_at}."""
    posts = thread_json.get("post_stream", {}).get("posts", [])
    topic_id = thread_json.get("id")

    result = []
    for p in posts:
        result.append({
            "id": p["id"],
            "topic_id": topic_id,
            "post_number": p["post_number"],
            "username": p["username"],
            "content": strip_html(p["cooked"]),
            "created_at": p["created_at"],
        })
    return result


if __name__ == "__main__":
    # Test 1 — strip_html on known text
    test_html = '<p>Voting FOR. Sad to read proposals like this one.</p>'
    print(strip_html(test_html))
    print()

    # Test 2 — fetch a real thread + extract posts
    thread = fetch_thread(
        "https://forum.arbitrum.foundation/t/"
        "banning-projects-identified-in-the-high-severity-watchdog-program-cases/31407"
    )
    print("Title:", thread["title"])
    print("Number of posts:", len(thread["post_stream"]["posts"]))
    print()

    posts = extract_posts(thread)
    for post in posts:
        print(f"[{post['post_number']}] {post['username']}: {post['content'][:80]}...")