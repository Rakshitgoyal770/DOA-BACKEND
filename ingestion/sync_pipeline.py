# ingestion/sync_pipeline.py
"""
DAO Governance Intelligence — Automated Sync & Audit Pipeline
=============================================================

This module inspects what data has been collected, what dates they span,
identifies missing pieces (e.g., proposals lacking votes or forum posts),
and automatically fetches new updates from Snapshot GraphQL and Discourse forums.

Usage:
    # 1. Audit status & show what is collected and what is missing:
    python -m ingestion.sync_pipeline --check

    # 2. Fetch new proposals, missing votes, and forum updates:
    python -m ingestion.sync_pipeline --sync-all

    # 3. Fetch missing votes only:
    python -m ingestion.sync_pipeline --fetch-votes --limit 10
"""

import argparse
import datetime
import json
import logging
import sys
import time
from typing import Dict, Any, List

from config.curated_daos import CURATED_DAOS
from db.schema import get_connection
from ingestion.discourse_client import fetch_thread, extract_posts
from ingestion.snapshot_client import get_proposals, get_votes, get_space, run_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_pipeline")


# ── 1. Audit / Status Inspection ───────────────────────────────────────────────

def audit_collection_status(conn) -> Dict[str, Any]:
    """
    Inspects what data is stored in SQLite:
    - Collection timestamps (fetched_at)
    - Date ranges of governance proposals and forum posts
    - Missing votes & missing forum posts
    - Comparison with latest Snapshot metrics
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Spaces overview
    spaces_rows = conn.execute("SELECT * FROM spaces").fetchall()
    spaces_info = []
    for s in spaces_rows:
        spaces_info.append({
            "id": s["id"],
            "name": s["name"],
            "network": s["network"],
            "fetched_at": s["fetched_at"]
        })

    # 2. Proposals per DAO space
    prop_stats = conn.execute("""
        SELECT 
            space_id,
            COUNT(*) as count,
            MIN(start_ts) as min_start,
            MAX(start_ts) as max_start,
            MIN(fetched_at) as first_fetched,
            MAX(fetched_at) as last_fetched,
            SUM(CASE WHEN state = 'active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN state = 'closed' THEN 1 ELSE 0 END) as closed_count,
            SUM(CASE WHEN discussion_url IS NOT NULL AND discussion_url != '' THEN 1 ELSE 0 END) as with_forum_url
        FROM proposals
        GROUP BY space_id
    """).fetchall()

    dao_summaries = []
    for r in prop_stats:
        min_date_str = (
            datetime.datetime.fromtimestamp(r["min_start"], tz=datetime.timezone.utc).strftime("%Y-%m-%d")
            if r["min_start"] else "N/A"
        )
        max_date_str = (
            datetime.datetime.fromtimestamp(r["max_start"], tz=datetime.timezone.utc).strftime("%Y-%m-%d")
            if r["max_start"] else "N/A"
        )
        dao_summaries.append({
            "space_id": r["space_id"],
            "count": r["count"],
            "date_range": f"{min_date_str} to {max_date_str}",
            "active_count": r["active_count"],
            "closed_count": r["closed_count"],
            "with_forum_url": r["with_forum_url"],
            "last_fetched": r["last_fetched"][:19] if r["last_fetched"] else "N/A"
        })

    # 3. Votes status
    vote_summary = conn.execute("""
        SELECT 
            COUNT(DISTINCT proposal_id) as props_with_votes,
            COUNT(*) as total_votes,
            MIN(created_ts) as min_ts,
            MAX(created_ts) as max_ts,
            MIN(fetched_at) as min_fetched,
            MAX(fetched_at) as max_fetched
        FROM votes
    """).fetchone()

    min_vote_str = (
        datetime.datetime.fromtimestamp(vote_summary["min_ts"], tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if vote_summary["min_ts"] else "N/A"
    )
    max_vote_str = (
        datetime.datetime.fromtimestamp(vote_summary["max_ts"], tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        if vote_summary["max_ts"] else "N/A"
    )

    # 4. Forum posts status
    forum_summary = conn.execute("""
        SELECT 
            COUNT(DISTINCT proposal_id) as props_with_posts,
            COUNT(*) as total_posts,
            MIN(created_at) as min_created,
            MAX(created_at) as max_created,
            MIN(fetched_at) as min_fetched,
            MAX(fetched_at) as max_fetched
        FROM forum_posts
    """).fetchone()

    # 5. Gaps & Missing Items
    total_proposals = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]

    # Proposals without votes
    missing_votes_count = conn.execute("""
        SELECT COUNT(*) FROM proposals p
        LEFT JOIN votes v ON p.id = v.proposal_id
        WHERE v.proposal_id IS NULL
    """).fetchone()[0]

    # Proposals with forum URL but no forum posts
    missing_forum_posts_count = conn.execute("""
        SELECT COUNT(*) FROM proposals p
        LEFT JOIN forum_posts f ON p.id = f.proposal_id
        WHERE p.discussion_url IS NOT NULL AND p.discussion_url != ''
        AND f.id IS NULL
    """).fetchone()[0]

    return {
        "audit_timestamp": now_utc.isoformat(),
        "total_proposals": total_proposals,
        "spaces": spaces_info,
        "daos": dao_summaries,
        "votes": {
            "total_votes": vote_summary["total_votes"],
            "proposals_with_votes": vote_summary["props_with_votes"],
            "proposals_missing_votes": missing_votes_count,
            "date_range": f"{min_vote_str} to {max_vote_str}",
            "last_fetched": vote_summary["max_fetched"][:19] if vote_summary["max_fetched"] else "N/A"
        },
        "forum": {
            "total_posts": forum_summary["total_posts"],
            "proposals_with_posts": forum_summary["props_with_posts"],
            "proposals_missing_posts": missing_forum_posts_count,
            "date_range": f"{forum_summary['min_created'][:10] if forum_summary['min_created'] else 'N/A'} to {forum_summary['max_created'][:10] if forum_summary['max_created'] else 'N/A'}",
            "last_fetched": forum_summary["max_fetched"][:19] if forum_summary["max_fetched"] else "N/A"
        }
    }


def print_audit_report(audit_data: Dict[str, Any]):
    """Pretty prints the audit status to the console."""
    print("=" * 70)
    print("        DAO GOVERNANCE INTELLIGENCE — DATA COLLECTION AUDIT       ")
    print("=" * 70)
    print(f"Audit Run At: {audit_data['audit_timestamp']}")
    print(f"Total Proposals in Database: {audit_data['total_proposals']}")
    print("-" * 70)
    print(f"{'DAO Space':<25} {'Props':<6} {'Dates Covered':<24} {'Last Fetched'}")
    print("-" * 70)
    for d in audit_data["daos"]:
        print(f"{d['space_id']:<25} {d['count']:<6} {d['date_range']:<24} {d['last_fetched']}")
    print("-" * 70)
    print("\n[VOTES DATA]")
    v = audit_data["votes"]
    print(f"  Total Votes Ingested: {v['total_votes']}")
    print(f"  Proposals with Votes: {v['proposals_with_votes']} / {audit_data['total_proposals']}")
    print(f"  Proposals MISSING Votes: {v['proposals_missing_votes']} (need ingestion for concentration analysis)")
    print(f"  Vote Dates Covered: {v['date_range']}")
    print(f"  Last Vote Fetch: {v['last_fetched']}")

    print("\n[FORUM DISCUSSIONS DATA]")
    f = audit_data["forum"]
    print(f"  Total Forum Posts: {f['total_posts']}")
    print(f"  Proposals with Posts: {f['proposals_with_posts']} / {audit_data['total_proposals']}")
    print(f"  Proposals with Discussion URL but NO Posts: {f['proposals_missing_posts']}")
    print(f"  Forum Posts Date Range: {f['date_range']}")
    print(f"  Last Forum Fetch: {f['last_fetched']}")
    print("=" * 70)


# ── 2. Ingestion & Automated Updates ──────────────────────────────────────────

def fetch_new_proposals(conn, first_per_dao: int = 10) -> Dict[str, int]:
    """
    Fetches the latest proposals from Snapshot GraphQL for all curated DAOs.
    - Inserts newly published proposals
    - Updates previously 'active' proposals to 'closed' once voting ends
    """
    logger.info(f"Checking Snapshot for new proposals across {len(CURATED_DAOS)} DAOs (latest {first_per_dao} each)...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inserted_count = 0
    updated_count = 0

    for dao in CURATED_DAOS:
        space_id = dao["id"]
        try:
            proposals = get_proposals(space_id, first=first_per_dao, skip=0)
            for p in proposals:
                # Check if exists
                existing = conn.execute(
                    "SELECT id, state, votes_count FROM proposals WHERE id = ?", (p["id"],)
                ).fetchone()

                if existing is None:
                    # New proposal
                    conn.execute("""
                        INSERT INTO proposals
                            (id, space_id, title, body, choices_json, state, votes_count,
                             scores_json, scores_total, start_ts, end_ts, link,
                             discussion_url, author, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        p["id"], space_id, p["title"], p["body"],
                        json.dumps(p["choices"]), p["state"], p["votes"],
                        json.dumps(p["scores"]), p["scores_total"],
                        p["start"], p["end"], p["link"], p.get("discussion"),
                        p["author"], now
                    ))
                    inserted_count += 1
                else:
                    # Update status or scores if state changed or votes increased
                    if existing["state"] != p["state"] or existing["votes_count"] != p["votes"]:
                        conn.execute("""
                            UPDATE proposals SET
                                state = ?,
                                votes_count = ?,
                                scores_json = ?,
                                scores_total = ?,
                                fetched_at = ?
                            WHERE id = ?
                        """, (
                            p["state"], p["votes"], json.dumps(p["scores"]),
                            p["scores_total"], now, p["id"]
                        ))
                        updated_count += 1
            conn.commit()
            logger.info(f"  [{dao['name']}] Synced {len(proposals)} proposals.")
        except Exception as e:
            logger.error(f"  [{dao['name']}] Failed to fetch proposals: {e}")

    return {"inserted": inserted_count, "updated": updated_count}


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


def fetch_missing_votes(conn, max_proposals: int = 10, votes_per_prop: int = 500) -> Dict[str, int]:
    """
    Fetches votes for proposals in SQLite that currently have 0 votes recorded.
    """
    targets = conn.execute("""
        SELECT p.id, p.title, p.space_id, p.votes_count
        FROM proposals p
        LEFT JOIN votes v ON p.id = v.proposal_id
        WHERE v.proposal_id IS NULL AND p.votes_count > 0
        ORDER BY p.votes_count DESC
        LIMIT ?
    """, (max_proposals,)).fetchall()

    logger.info(f"Ingesting votes for {len(targets)} proposals with missing vote records...")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total_votes_ingested = 0
    props_done = 0

    for p in targets:
        try:
            votes = get_votes(p["id"], first=votes_per_prop, skip=0)
            for v in votes:
                vote_key = f"{p['id']}_{v['voter']}"
                conn.execute("""
                    INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vote_key) DO UPDATE SET
                        choice_json = excluded.choice_json,
                        vp = excluded.vp,
                        fetched_at = excluded.fetched_at
                """, (
                    vote_key, p["id"], v["voter"], json.dumps(v["choice"]),
                    v["vp"], v["created"], now
                ))
            conn.commit()
            props_done += 1
            total_votes_ingested += len(votes)
            logger.info(f"  + {len(votes)} votes for [{p['space_id']}] '{p['title'][:40]}'")
            time.sleep(0.2)  # Avoid Snapshot rate limiting
        except Exception as e:
            logger.error(f"  Failed votes for {p['id']}: {e}")

    return {"proposals_completed": props_done, "votes_ingested": total_votes_ingested}


def sync_all(conn, proposals_first: int = 10, votes_proposals_limit: int = 10) -> Dict[str, Any]:
    """
    Executes a complete sync:
    1. Fetches new proposals & updates active ones
    2. Fetches missing forum discussions
    3. Fetches missing votes
    4. Audits updated status
    """
    logger.info("=== STARTING FULL DATA SYNC ===")
    prop_res = fetch_new_proposals(conn, first_per_dao=proposals_first)
    forum_res = fetch_missing_forum_posts(conn, limit=20)
    vote_res = fetch_missing_votes(conn, max_proposals=votes_proposals_limit, votes_per_prop=500)
    audit = audit_collection_status(conn)
    logger.info("=== SYNC COMPLETED SUCCESSFULLY ===")
    return {
        "proposals": prop_res,
        "forum_posts_added": forum_res,
        "votes": vote_res,
        "current_status": audit
    }


# ── CLI Interface ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAO Governance Data Audit & Sync")
    parser.add_argument("--check", action="store_true", help="Print audit report of collected dates and missing items")
    parser.add_argument("--sync-all", action="store_true", help="Fetch new proposals, missing forum posts, and missing votes")
    parser.add_argument("--fetch-proposals", action="store_true", help="Fetch new proposals from Snapshot")
    parser.add_argument("--fetch-votes", action="store_true", help="Fetch missing votes for proposals")
    parser.add_argument("--fetch-forum", action="store_true", help="Fetch missing forum posts")
    parser.add_argument("--limit", type=int, default=10, help="Batch limit for votes or proposals (default: 10)")

    args = parser.parse_args()
    conn = get_connection()

    if args.sync_all:
        res = sync_all(conn, proposals_first=args.limit, votes_proposals_limit=args.limit)
        print_audit_report(res["current_status"])
    elif args.fetch_proposals:
        res = fetch_new_proposals(conn, first_per_dao=args.limit)
        print(f"Proposals sync complete: {res}")
    elif args.fetch_votes:
        res = fetch_missing_votes(conn, max_proposals=args.limit)
        print(f"Votes sync complete: {res}")
    elif args.fetch_forum:
        res = fetch_missing_forum_posts(conn, limit=args.limit)
        print(f"Forum sync complete: {res} posts ingested")
    else:
        # Default action is check
        audit = audit_collection_status(conn)
        print_audit_report(audit)

    conn.close()
