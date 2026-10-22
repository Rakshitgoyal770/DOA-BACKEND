# features/sync/audit.py
"""
features/sync/audit.py — Reports what data we have, how fresh it is, and what is incomplete.

WHAT THIS FILE DOES
    audit_collection_status() reads SQLite (never the network) and summarises:
      * per DAO: number of proposals, date range, last fetch
      * votes:   totals, date range, and COMPLETENESS (stored vs Snapshot's count,
                 rule in features/votes/completeness.py)
      * forum:   totals, date range, and COMPLETENESS (stored vs what Discourse
                 listed, rule in features/forum/completeness.py)
    print_audit_report() prints the same dict for the command line.

WHERE IT SITS
    GET /sync/status (features/sync/routes.py) ──┐
    sync_all() and --check (features/sync/runner.py) ┴─> THIS FILE ─> SQLite (read-only)

INPUTS
    conn - an open SQLite connection, passed in by the callers above.
"""

import datetime
from collections import Counter
from typing import Any, Dict

from features.forum import completeness as forum_status
from features.forum.completeness import forum_completeness
from features.votes.completeness import COMPLETE, MISSING, NO_VOTES, PARTIAL, vote_completeness

MAX_LISTED_INCOMPLETE = 10   # how many incomplete proposals the audit names


def audit_collection_status(conn) -> Dict[str, Any]:
    """
    The full audit as a dict: audit_timestamp, total_proposals, spaces, daos,
    votes {..., completeness}, forum {..., completeness}.

    Parameter (where it comes from):
        conn - opened by get_sync_status() (GET /sync/status), or passed by
               sync_all() / the --check CLI branch in features/sync/runner.py.
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

    # Vote completeness: stored votes vs. Snapshot's count, per proposal
    completeness = vote_completeness(conn)
    status_counts = Counter(r["status"] for r in completeness)
    incomplete = sorted(
        (r for r in completeness if r["status"] in (MISSING, PARTIAL)),
        key=lambda r: r["expected"] - r["stored"],
        reverse=True,
    )

    # Forum completeness: stored posts vs. what Discourse listed, per thread
    threads = forum_completeness(conn)
    thread_counts = Counter(t["status"] for t in threads)
    incomplete_threads = sorted(
        (t for t in threads if t["status"] != forum_status.COMPLETE),
        key=lambda t: t["listed"] - t["stored"],
        reverse=True,
    )

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
            "proposals_missing_votes": status_counts[MISSING],
            "date_range": f"{min_vote_str} to {max_vote_str}",
            "last_fetched": vote_summary["max_fetched"][:19] if vote_summary["max_fetched"] else "N/A",
            "completeness": {
                "complete": status_counts[COMPLETE],
                "partial": status_counts[PARTIAL],
                "missing": status_counts[MISSING],
                "no_votes_on_snapshot": status_counts[NO_VOTES],
                "is_complete": not incomplete,
                "incomplete_proposals": [
                    {k: r[k] for k in ("proposal_id", "space_id", "title", "stored", "expected", "status")}
                    for r in incomplete[:MAX_LISTED_INCOMPLETE]
                ],
            },
        },
        "forum": {
            "total_posts": forum_summary["total_posts"],
            "proposals_with_posts": forum_summary["props_with_posts"],
            "proposals_missing_posts": missing_forum_posts_count,
            "date_range": f"{forum_summary['min_created'][:10] if forum_summary['min_created'] else 'N/A'} to {forum_summary['max_created'][:10] if forum_summary['max_created'] else 'N/A'}",
            "last_fetched": forum_summary["max_fetched"][:19] if forum_summary["max_fetched"] else "N/A",
            "completeness": {
                "threads": len(threads),
                "complete": thread_counts[forum_status.COMPLETE],
                "partial": thread_counts[forum_status.PARTIAL],
                "not_fetched": thread_counts[forum_status.NOT_FETCHED],
                "error": thread_counts[forum_status.ERROR],
                "shared_threads": sum(1 for t in threads if len(t["proposal_ids"]) > 1),
                "is_complete": not incomplete_threads,
                "incomplete_threads": [
                    {k: t[k] for k in ("url", "status", "stored", "listed", "unavailable", "last_error")}
                    for t in incomplete_threads[:MAX_LISTED_INCOMPLETE]
                ],
            },
        }
    }


def print_audit_report(audit_data: Dict[str, Any]):
    """
    Print the audit for a person reading the terminal.

    Parameter (where it comes from):
        audit_data - the dict returned by audit_collection_status(), passed by the
                     --check and --sync-all branches of features/sync/runner.py.
    """
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
    c = v["completeness"]
    print(f"  Complete: {c['complete']} | Partial: {c['partial']} | Missing: {c['missing']} "
          f"| No votes on Snapshot: {c['no_votes_on_snapshot']}")
    for r in c["incomplete_proposals"]:
        print(f"    - {r['status']:<8} {r['stored']:>6}/{r['expected']:<6} [{r['space_id']}] {r['title'][:40]}")
    print(f"  Vote Dates Covered: {v['date_range']}")
    print(f"  Last Vote Fetch: {v['last_fetched']}")

    print("\n[FORUM DISCUSSIONS DATA]")
    f = audit_data["forum"]
    print(f"  Total Forum Posts: {f['total_posts']}")
    print(f"  Proposals with Posts: {f['proposals_with_posts']} / {audit_data['total_proposals']}")
    print(f"  Proposals with Discussion URL but NO Posts: {f['proposals_missing_posts']}")
    fc = f["completeness"]
    print(f"  Threads: {fc['threads']} | Complete: {fc['complete']} | Partial: {fc['partial']} "
          f"| Not fetched: {fc['not_fetched']} | Error: {fc['error']} | Shared by >1 proposal: {fc['shared_threads']}")
    for t in fc["incomplete_threads"]:
        print(f"    - {t['status']:<11} {t['stored']:>4}/{t['listed']:<4} {t['url'][-55:]}")
    print(f"  Forum Posts Date Range: {f['date_range']}")
    print(f"  Last Forum Fetch: {f['last_fetched']}")
    print("=" * 70)


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller: the JSON response of GET /sync/status, the end of
# sync_all(), or the printed report of the CLI.
# If the audit shows incomplete data: run python -m features.sync.runner with
#   --fetch-votes / --fetch-forum (add --limit 200 for a large backfill).
