# tests/helpers.py
"""Small helpers that insert just the columns a test cares about."""

import json


def add_proposal(conn, pid, space_id="test.eth", votes_count=0, title=None, body="",
                 choices=("For", "Against"), scores=None, start_ts=1_700_000_000,
                 end_ts=1_700_100_000, state="closed", discussion_url=None):
    conn.execute(
        """INSERT INTO proposals (id, space_id, title, body, choices_json, scores_json,
                                  scores_total, votes_count, start_ts, end_ts, state, discussion_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pid, space_id, title or f"Proposal {pid}", body, json.dumps(list(choices)),
         json.dumps(scores) if scores else None, sum(scores) if scores else None,
         votes_count, start_ts, end_ts, state, discussion_url),
    )
    conn.commit()


def add_votes(conn, pid, n, first_ts=1_700_000_000, voter_prefix="0xVoter", vp=1.0):
    """Insert `n` votes with one-second steps: voters <prefix>0, <prefix>1, ..."""
    rows = [(f"{pid}_{voter_prefix}{i}", pid, f"{voter_prefix}{i}", "1", vp, first_ts + i, "t")
            for i in range(n)]
    conn.executemany(
        "INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()


def add_post(conn, post_id, pid, username, content):
    conn.execute(
        "INSERT INTO forum_posts (id, proposal_id, username, content) VALUES (?, ?, ?, ?)",
        (post_id, pid, username, content))
    conn.commit()


def add_identity(conn, username, wallet, confidence="medium", method="ens_username"):
    conn.execute(
        "INSERT INTO resolved_identities (forum_username, wallet_address, confidence_level, "
        "resolution_method, resolved_at) VALUES (?, ?, ?, ?, 't')",
        (username, wallet, confidence, method))
    conn.commit()


def count(conn, table, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
