# tests/test_forum.py
"""Complete forum threads: pagination, shared threads, post-id collisions,
refresh, errors, completeness, and the one-time schema migration."""

import datetime
import re
import sqlite3

import pytest

import clients.discourse as discourse
import db.schema as schema
from features.forum.completeness import forum_completeness
from features.forum.fetch import fetch_forum_threads
from features.sync.audit import audit_collection_status
from tests.helpers import add_proposal, count

NOW = datetime.datetime.now(datetime.timezone.utc).timestamp()


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeForum:
    """Behaves like Discourse: a thread page holds the first 20 posts plus every
    post id; /t/<id>/posts.json returns the requested ids. Threads are keyed by
    (forum host, topic id), because ids are only unique inside one forum."""

    def __init__(self):
        self.threads = {}
        self.calls = []        # every URL requested
        self.broken = set()    # (host, topic) pairs that raise an error

    def add_thread(self, host, topic, n_posts, first_post_id=1000, text="post", deleted=()):
        posts = [{"id": first_post_id + i, "post_number": i + 1, "username": f"user{i % 5}",
                  "cooked": f"<p>{text} {i}</p>", "created_at": "2026-01-01T00:00:00Z"}
                 for i in range(n_posts)]
        self.threads[(host, topic)] = {"posts": posts, "deleted": set(deleted)}
        return f"https://{host}/t/some-slug/{topic}"

    def add_posts(self, host, topic, n):
        posts = self.threads[(host, topic)]["posts"]
        last = posts[-1]
        posts.extend({**last, "id": last["id"] + 1 + i, "post_number": last["post_number"] + 1 + i}
                     for i in range(n))

    def get(self, url, params=None, **_):
        self.calls.append(url)
        host, topic, kind = re.match(r"https://([^/]+)/t/(?:[^/]+/)?(\d+)(\.json|/posts\.json)$", url).groups()
        if (host, int(topic)) in self.broken:
            raise ConnectionError("forum is down")
        t = self.threads[(host, int(topic))]
        visible = [p for p in t["posts"] if p["id"] not in t["deleted"]]
        if kind == ".json":
            return FakeResponse({"id": int(topic),
                                 "post_stream": {"posts": visible[:20], "stream": [p["id"] for p in t["posts"]]}})
        wanted = {int(v) for _, v in params}
        return FakeResponse({"post_stream": {"posts": [p for p in visible if p["id"] in wanted]}})

    def page_requests(self):
        return [u for u in self.calls if u.endswith("/posts.json")]


@pytest.fixture
def forum(monkeypatch):
    fake = FakeForum()
    monkeypatch.setattr(discourse.requests, "get", fake.get)
    monkeypatch.setattr(discourse.time, "sleep", lambda s: None)
    return fake


def thread_row(conn, proposal_id):
    return next(t for t in forum_completeness(conn) if proposal_id in t["proposal_ids"])


# ── URL normalization ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, expected", [
    ("https://gov.a.org/t/slug/123", "https://gov.a.org/t/slug/123.json"),
    ("https://gov.a.org/t/slug/123/42?u=bob", "https://gov.a.org/t/slug/123.json"),
    ("https://gov.a.org/t/name-only-slug", "https://gov.a.org/t/name-only-slug.json"),
])
def test_normalize_url_is_safe_to_apply_twice(url, expected):
    once = discourse.normalize_discourse_url(url)
    assert once == expected
    assert discourse.normalize_discourse_url(once) == expected     # was ".json.json" for name-only links


# ── fetching every post ───────────────────────────────────────────────────────

def test_fetches_every_post_not_just_the_first_20(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=45)
    add_proposal(db, "P", discussion_url=url)
    assert thread_row(db, "P")["status"] == "not_fetched"

    result = fetch_forum_threads(db)

    assert count(db, "forum_posts", "proposal_id = 'P'") == 45
    assert len(forum.page_requests()) == 2               # 25 remaining posts = 20 + 5
    assert thread_row(db, "P")["status"] == "complete"
    assert result == {"threads_processed": 1, "posts_written": 45, "failed": []}


def test_a_shared_thread_is_fetched_once_and_stored_for_every_proposal(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=30)
    add_proposal(db, "P1", discussion_url=url)
    add_proposal(db, "P2", discussion_url=url + "?u=someone")   # same thread, different link

    fetch_forum_threads(db)

    assert count(db, "forum_posts", "proposal_id = 'P1'") == 30
    assert count(db, "forum_posts", "proposal_id = 'P2'") == 30
    assert len([u for u in forum.calls if u.endswith(".json") and "posts" not in u]) == 1
    assert thread_row(db, "P1")["proposal_ids"] == ["P1", "P2"]


def test_proposal_linking_an_already_fetched_thread_gets_every_post(db, forum):
    """Real case: 3 threads were linked by several proposals, but posts were
    stored for only one of them. The newcomer must get all posts, not page 1."""
    url = forum.add_thread("gov.a.org", 1, n_posts=30)
    add_proposal(db, "FIRST", discussion_url=url)
    fetch_forum_threads(db)
    add_proposal(db, "LATER", discussion_url=url)

    fetch_forum_threads(db)

    assert count(db, "forum_posts", "proposal_id = 'LATER'") == 30
    assert thread_row(db, "LATER")["status"] == "complete"


def test_same_post_id_on_two_forums_keeps_both_posts(db, forum):
    url_a = forum.add_thread("gov.a.org", 1, n_posts=3, first_post_id=500, text="forum A")
    url_b = forum.add_thread("gov.b.org", 1, n_posts=3, first_post_id=500, text="forum B")
    add_proposal(db, "PA", discussion_url=url_a)
    add_proposal(db, "PB", discussion_url=url_b)

    fetch_forum_threads(db)

    texts = dict(db.execute("SELECT proposal_id, content FROM forum_posts WHERE id = 500"))
    assert texts == {"PA": "forum A 0", "PB": "forum B 0"}       # the old key overwrote one of them


def test_deleted_post_counts_as_unavailable_not_missing(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=25, deleted={1022})
    add_proposal(db, "P", discussion_url=url)

    fetch_forum_threads(db)

    row = thread_row(db, "P")
    assert (row["stored"], row["listed"], row["unavailable"], row["status"]) == (24, 25, 1, "complete")


# ── refreshing and failures ──────────────────────────────────────────────────

def _age_last_fetch(conn, days):
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    conn.execute("UPDATE forum_threads SET last_fetched_at = ?", (old,))
    conn.commit()


def test_recent_thread_is_rechecked_and_only_new_posts_are_downloaded(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=45)
    add_proposal(db, "P", discussion_url=url, state="active", end_ts=int(NOW) + 86_400)
    fetch_forum_threads(db)
    _age_last_fetch(db, days=2)
    forum.add_posts("gov.a.org", 1, 3)
    forum.calls.clear()

    fetch_forum_threads(db)

    assert count(db, "forum_posts") == 48
    assert len(forum.page_requests()) == 1                      # only the 3 new ids
    assert forum.calls[-1].endswith("/posts.json")


def test_old_complete_thread_is_not_refetched(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=5)
    add_proposal(db, "P", discussion_url=url, end_ts=1_600_000_000)   # ended in 2020
    fetch_forum_threads(db)
    _age_last_fetch(db, days=30)
    forum.calls.clear()

    assert fetch_forum_threads(db)["threads_processed"] == 0
    assert forum.calls == []


def test_a_failing_thread_is_recorded_and_retried(db, forum):
    url_bad = forum.add_thread("gov.a.org", 1, n_posts=5)
    url_ok = forum.add_thread("gov.a.org", 2, n_posts=5, first_post_id=2000)
    add_proposal(db, "BAD", discussion_url=url_bad)
    add_proposal(db, "OK", discussion_url=url_ok)
    forum.broken.add(("gov.a.org", 1))

    first = fetch_forum_threads(db)

    assert len(first["failed"]) == 1
    assert thread_row(db, "BAD")["status"] == "error"
    assert "forum is down" in thread_row(db, "BAD")["last_error"]
    assert thread_row(db, "OK")["status"] == "complete"

    forum.broken.clear()
    fetch_forum_threads(db)
    assert thread_row(db, "BAD")["status"] == "complete"
    assert thread_row(db, "BAD")["last_error"] is None


def test_second_run_does_nothing_when_nothing_changed(db, forum):
    url = forum.add_thread("gov.a.org", 1, n_posts=45)
    add_proposal(db, "P", discussion_url=url, end_ts=1_600_000_000)
    fetch_forum_threads(db)
    forum.calls.clear()

    assert fetch_forum_threads(db)["threads_processed"] == 0
    assert forum.calls == []


# ── audit ─────────────────────────────────────────────────────────────────────

def test_audit_reports_forum_completeness(db, forum):
    url_done = forum.add_thread("gov.a.org", 1, n_posts=3)
    url_shared = forum.add_thread("gov.a.org", 2, n_posts=3, first_post_id=2000)
    url_later = forum.add_thread("gov.a.org", 3, n_posts=3, first_post_id=3000)
    add_proposal(db, "A", discussion_url=url_done)
    add_proposal(db, "B1", discussion_url=url_shared)
    add_proposal(db, "B2", discussion_url=url_shared)
    add_proposal(db, "G", discussion_url="https://gist.github.com/someone/abc")   # not a forum thread
    fetch_forum_threads(db, limit=2)
    add_proposal(db, "C", discussion_url=url_later)

    c = audit_collection_status(db)["forum"]["completeness"]

    assert (c["threads"], c["complete"], c["not_fetched"], c["shared_threads"]) == (3, 2, 1, 1)
    assert c["is_complete"] is False


# ── one-time migration of older databases ────────────────────────────────────

def test_old_forum_posts_table_is_migrated_without_losing_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE forum_posts (id INTEGER PRIMARY KEY, proposal_id TEXT, topic_id INTEGER,
            post_number INTEGER, username TEXT, content TEXT, created_at TEXT, fetched_at TEXT);
        INSERT INTO forum_posts VALUES (1, 'P', 9, 1, 'alice', 'hello', 't', 't');
        INSERT INTO forum_posts VALUES (2, 'P', 9, 2, 'bob', 'world', 't', 't');
    """)
    old.close()
    monkeypatch.setattr(schema, "DB_PATH", path)

    conn = schema.get_connection()
    schema.get_connection().close()                       # a second connection must not migrate again

    key = [r[1] for r in sorted(conn.execute("PRAGMA table_info(forum_posts)"), key=lambda r: r[5]) if r[5]]
    assert key == ["proposal_id", "id"]
    assert [tuple(r) for r in conn.execute("SELECT id, username, content FROM forum_posts ORDER BY id")] == \
        [(1, "alice", "hello"), (2, "bob", "world")]
    conn.execute("INSERT INTO forum_posts (id, proposal_id) VALUES (1, 'OTHER')")   # now allowed
    assert "idx_forum_proposal" in {r[1] for r in conn.execute("PRAGMA index_list(forum_posts)")}
    conn.close()
