# db/schema.py
"""
SQLite schema for local dev. Swap to Postgres later by changing only the
connection setup — table definitions here are portable standard SQL.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "dao_intelligence.db"

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

CREATE TABLE IF NOT EXISTS forum_posts (
    id              INTEGER PRIMARY KEY,   -- Discourse post id
    proposal_id     TEXT REFERENCES proposals(id),
    topic_id        INTEGER,
    post_number     INTEGER,
    username        TEXT,
    content         TEXT,                  -- HTML-stripped 'cooked' field
    created_at      TEXT,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS resolved_identities (
    forum_username      TEXT PRIMARY KEY,
    wallet_address       TEXT,
    confidence_level     TEXT,             -- 'certain' | 'high' | 'medium' | 'low' | 'unresolved'
    resolution_method    TEXT,             -- 'verified' | 'sso' | 'registry' | 'ens' | 'self_disclosed' | 'none'
    resolved_at           TEXT
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
CREATE INDEX IF NOT EXISTS idx_forum_proposal ON forum_posts(proposal_id);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.row_factory = sqlite3.Row   # lets you access columns by name, e.g. row["title"]
    return conn


if __name__ == "__main__":
    init_db()