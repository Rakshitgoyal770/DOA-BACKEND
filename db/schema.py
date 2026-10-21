# db/schema.py
"""
SQLite schema for local dev. Swap to Postgres later by changing only the
connection setup — table definitions here are portable standard SQL.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "dao_intelligence.db"

# A forum post is stored once per proposal that links its thread:
#  * Discourse post ids are only unique inside ONE forum (Optimism's post 13884
#    and Aave's post 13884 are different posts), and a proposal links exactly
#    one thread, so (proposal_id, id) is always unique.
#  * Several proposals can link the same thread; each gets its own copy, so
#    every "posts of proposal X" query stays a simple WHERE proposal_id = ?.
FORUM_POSTS_TABLE = """
CREATE TABLE IF NOT EXISTS forum_posts (
    id              INTEGER NOT NULL,      -- Discourse post id (unique within one forum only)
    proposal_id     TEXT NOT NULL REFERENCES proposals(id),
    topic_id        INTEGER,
    post_number     INTEGER,
    username        TEXT,
    content         TEXT,                  -- HTML-stripped 'cooked' field
    created_at      TEXT,
    fetched_at      TEXT,
    PRIMARY KEY (proposal_id, id)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS spaces (
    id              TEXT PRIMARY KEY,      -- e.g. 'arbitrumfoundation.eth'
    name            TEXT,
    about           TEXT,
    network         TEXT,
    proposals_count INTEGER,
    followers_count INTEGER,
    votes_count     INTEGER,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
    id              TEXT PRIMARY KEY,      -- Snapshot proposal id (0x...)
    space_id        TEXT REFERENCES spaces(id),
    title           TEXT,
    body            TEXT,
    choices_json    TEXT,                  -- JSON array, e.g. '["FOR","AGAINST","ABSTAIN"]'
    state           TEXT,                  -- 'active' | 'closed' | 'pending'
    votes_count     INTEGER,
    scores_json     TEXT,                  -- JSON array, positionally matches choices
    scores_total    REAL,
    start_ts        INTEGER,
    end_ts          INTEGER,
    link            TEXT,
    discussion_url  TEXT,                  -- links to Discourse thread, when Snapshot has it
    author          TEXT,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS votes (
    vote_key        TEXT PRIMARY KEY,
    proposal_id     TEXT REFERENCES proposals(id),
    voter           TEXT,
    choice_json     TEXT,      -- was: choice INTEGER — now stores JSON (int, dict, or array)
    vp              REAL,
    created_ts      INTEGER,
    fetched_at      TEXT
);

""" + FORUM_POSTS_TABLE + """
-- One row per Discourse thread we fetch: what Discourse listed, so we can tell
-- whether every post was stored (like votes_count does for votes).
CREATE TABLE IF NOT EXISTS forum_threads (
    url             TEXT PRIMARY KEY,      -- thread JSON url, as normalize_discourse_url returns it
    topic_id        INTEGER,
    listed_posts    INTEGER,               -- post ids Discourse listed (post_stream.stream)
    unavailable     INTEGER DEFAULT 0,     -- listed ids Discourse did not return (deleted or hidden)
    last_fetched_at TEXT,                  -- last successful fetch
    last_error      TEXT                   -- NULL when the last attempt worked
);

CREATE TABLE IF NOT EXISTS resolved_identities (
    forum_username      TEXT PRIMARY KEY,
    wallet_address       TEXT,
    confidence_level     TEXT,             -- 'certain' | 'high' | 'medium' | 'low' | 'unresolved'
    resolution_method    TEXT,             -- 'verified' | 'sso' | 'registry' | 'ens' | 'self_disclosed' | 'none'
    resolved_at           TEXT
);

CREATE TABLE IF NOT EXISTS wallet_ens (
    wallet_address   TEXT PRIMARY KEY,
    ens_name         TEXT,                 -- NULL when the wallet has no primary name
    verified         INTEGER DEFAULT 0,    -- 1 if name resolves forward to the same wallet
    checked_at       TEXT
);

CREATE TABLE IF NOT EXISTS proposal_polling_state (
    proposal_id               TEXT PRIMARY KEY REFERENCES proposals(id),
    is_active                 INTEGER DEFAULT 0,   -- 0 or 1, SQLite has no real boolean type
    last_requested_at         TEXT,                -- most recent user request, drives idle eviction
    last_refreshed_at         TEXT,                -- most recent successful data pull
    refresh_interval_minutes  INTEGER DEFAULT 5
);

CREATE INDEX IF NOT EXISTS idx_proposals_space ON proposals(space_id);
CREATE INDEX IF NOT EXISTS idx_votes_proposal ON votes(proposal_id);
-- Wallet addresses arrive in mixed case, so lookups compare lower(voter);
-- this index lets "votes of wallet X on proposal Y" skip a full scan.
CREATE INDEX IF NOT EXISTS idx_votes_proposal_voter ON votes(proposal_id, lower(voter));
CREATE INDEX IF NOT EXISTS idx_forum_proposal ON forum_posts(proposal_id);
"""


def _migrate_forum_posts_key(conn):
    """
    Older databases keyed forum_posts by post id alone (see FORUM_POSTS_TABLE
    for why that is wrong). SQLite cannot change a primary key in place, so
    the table is rebuilt once and every row is copied unchanged. Later calls
    see the new key and do nothing.
    """
    key = [r[1] for r in sorted(conn.execute("PRAGMA table_info(forum_posts)"), key=lambda r: r[5]) if r[5]]
    if key != ["id"]:
        return
    conn.executescript("""
        BEGIN;
        ALTER TABLE forum_posts RENAME TO forum_posts_old;
    """ + FORUM_POSTS_TABLE + """
        INSERT INTO forum_posts (id, proposal_id, topic_id, post_number, username, content, created_at, fetched_at)
            SELECT id, proposal_id, topic_id, post_number, username, content, created_at, fetched_at
            FROM forum_posts_old;
        DROP TABLE forum_posts_old;
        CREATE INDEX IF NOT EXISTS idx_forum_proposal ON forum_posts(proposal_id);
        COMMIT;
    """)


def _ensure_schema(conn):
    conn.executescript(SCHEMA)
    _migrate_forum_posts_key(conn)
    conn.commit()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    _ensure_schema(conn)
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    _ensure_schema(conn)
    conn.row_factory = sqlite3.Row   # lets you access columns by name, e.g. row["title"]
    return conn


if __name__ == "__main__":
    init_db()