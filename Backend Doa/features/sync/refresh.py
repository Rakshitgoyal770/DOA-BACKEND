# features/sync/refresh.py
"""
features/sync/refresh.py — The whole "bring everything up to date" job, safe to run unattended.

WHAT THIS FILE DOES
    refresh() runs, in this order, what used to be four commands typed by hand:
        1. backup    a verified copy of the database in backups/ (the newest KEEP_BACKUPS are kept)
        2. sync      features/sync/runner.py sync_all, repeated until nothing is left to fetch
                     or a round brings nothing new (Snapshot + Discourse: network)
        3. identity  features/identity/runner.py rescore (offline: re-checks wallet links
                     against the votes now stored)
        4. index     vector/embedding.py sync_index (only new or changed text is embedded)
        5. check     vector/embedding.py check_index (every chunk's metadata is valid)
    and returns a report: what each step did, row counts before and after, "problems" (the run
    FAILED: look at it) and "warnings" (worth knowing, the run still counts as good).

    A step that fails does not stop the later ones: the fetchers record their own failures and
    the next run retries them, and the index should match the database whatever the sync managed.

    Only one refresh runs at a time (a lock file in logs/). Each run writes logs/refresh_<time>.log
    and logs/last_refresh.json, which is the file to look at to see whether the schedule is working.

COMMAND LINE
    python -m features.sync.refresh                 # the whole job
    python -m features.sync.refresh --no-backup     # skip step 1
    python -m features.sync.refresh --offline       # skip step 2 (no network): backup, identity, index, check
    Exit code: 0 good, 1 problems, 2 another refresh is already running.

SCHEDULE
    scripts/register_refresh_task.ps1 registers this command as a daily Windows scheduled task.

TO RESTORE A BACKUP
    Stop the API, then copy backups/dao_intelligence_<time>.db over db/dao_intelligence.db and
    run `python -m vector.embedding` so the index matches it again.

WHERE IT SITS
    the scheduled task / the command line --> THIS FILE --> sync runner, identity runner, vector/embedding.py
"""

import argparse
import datetime
import json
import logging
import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path

import db.schema as schema

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
BACKUP_DIR = ROOT / "backups"
LOG_DIR = ROOT / "logs"
LOCK_NAME = "refresh.lock"
REPORT_NAME = "last_refresh.json"

KEEP_BACKUPS = 5                 # database backups kept; older ones are deleted
KEEP_LOGS = 30                   # refresh logs kept
MAX_SYNC_ROUNDS = 6              # sync_all runs per refresh (each fetches a limited batch)
VOTES_PROPOSALS_PER_ROUND = 50   # proposals that get their votes per round
STALE_LOCK_SECONDS = 6 * 3600    # a lock older than this is from a run that died
MAX_SHRINK = 0.01                # a table losing more than 1% of its rows is a problem
COUNTED_TABLES = ("proposals", "votes", "forum_posts", "resolved_identities")


# ── Small building blocks ─────────────────────────────────────────────────────

def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def table_counts(conn) -> dict:
    """Rows per table we watch: {"proposals": 118, "votes": ..., ...}."""
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in COUNTED_TABLES}


def backup_database(db_path: Path, backup_dir: Path, keep: int = KEEP_BACKUPS) -> Path:
    """
    A consistent copy of the database (SQLite's own backup, safe while the API is reading),
    verified with an integrity check. Keeps the newest `keep` backups and deletes older ones.
    Raises if the copy is not a healthy database.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"dao_intelligence_{_stamp()}.db"
    source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
        verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        copy.close()
        source.close()
    if verdict != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed its integrity check: {verdict}")
    for old in sorted(backup_dir.glob("dao_intelligence_*.db"))[:-keep]:
        old.unlink()
    return target


def acquire_lock(log_dir: Path, stale_after: int = STALE_LOCK_SECONDS) -> Path | None:
    """
    The lock file, or None when another refresh holds it. A lock older than `stale_after`
    seconds belongs to a run that died and is taken over.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    lock = log_dir / LOCK_NAME
    if lock.exists() and time.time() - lock.stat().st_mtime > stale_after:
        lock.unlink()
    try:
        with open(lock, "x") as f:
            f.write(f"{os.getpid()} {datetime.datetime.now().isoformat()}")
    except FileExistsError:
        return None
    return lock


def _progress(audit: dict) -> tuple:
    """What a sync round can change. Two equal values in a row mean the round brought nothing."""
    return (audit["total_proposals"], audit["votes"]["total_votes"], audit["votes"]["completeness"]["complete"],
            audit["forum"]["total_posts"], audit["forum"]["completeness"]["complete"])


def sync_until_complete(conn, sync_all, audit, max_rounds: int = MAX_SYNC_ROUNDS,
                        votes_per_round: int = VOTES_PROPOSALS_PER_ROUND) -> dict:
    """
    Run sync_all until votes and forum are complete, a round changes nothing, or max_rounds.
    Returns {"rounds", "stopped_because", "votes_complete", "forum_complete", "incomplete"}.

    A thread that always fails (a deleted topic) keeps "forum_complete" false for ever; the
    "nothing new" rule is what stops the loop then, and it is reported as a warning, not a failure.
    """
    before = _progress(audit(conn))
    rounds, reason, status = 0, "max_rounds", None
    while rounds < max_rounds:
        status = sync_all(conn, votes_proposals_limit=votes_per_round)["current_status"]
        rounds += 1
        votes_ok = status["votes"]["completeness"]["is_complete"]
        forum_ok = status["forum"]["completeness"]["is_complete"]
        if votes_ok and forum_ok:
            reason = "complete"
            break
        now = _progress(status)
        if now == before:
            reason = "nothing_new"
            break
        before = now
    return {
        "rounds": rounds,
        "stopped_because": reason,
        "votes_complete": status["votes"]["completeness"]["is_complete"],
        "forum_complete": status["forum"]["completeness"]["is_complete"],
        "incomplete": {"proposals": status["votes"]["completeness"]["incomplete_proposals"],
                       "threads": status["forum"]["completeness"]["incomplete_threads"]},
    }


# ── The job ───────────────────────────────────────────────────────────────────

def refresh(backup: bool = True, online: bool = True, steps: dict | None = None,
            backup_dir: Path = BACKUP_DIR) -> dict:
    """
    The whole job (see the top of this file). Returns the report; report["ok"] is False when
    there are problems.

    Parameters:
        backup     - False skips the database backup (CLI --no-backup).
        online     - False skips the network sync (CLI --offline).
        steps      - the functions each step calls; tests pass fakes. Keys: sync_all, audit,
                     rescore, sync_index, check_index. Left out, the real ones are imported
                     here (importing them loads the fetchers, so it is not done at module level).
        backup_dir - where backups go.
    """
    if steps is None:
        from features.identity.runner import rescore
        from features.sync.audit import audit_collection_status
        from features.sync.runner import sync_all
        from vector.embedding import check_index, get_collection, sync_index
        steps = {"sync_all": sync_all, "audit": audit_collection_status, "rescore": rescore,
                 "sync_index": sync_index, "check_index": lambda: check_index(get_collection())}

    report = {"started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "steps": {},
              "problems": [], "warnings": []}

    def run(name, function):
        """Run one step; a failure becomes a problem and the job goes on."""
        logger.info("--- step: %s ---", name)
        try:
            report["steps"][name] = function()
            logger.info("%s: %s", name, json.dumps(report["steps"][name], default=str)[:2000])
            return report["steps"][name]
        except Exception as e:                                  # network down, disk full, a bug, ...
            report["problems"].append(f"{name} failed: {type(e).__name__}: {e}")
            logger.error("%s failed:\n%s", name, traceback.format_exc())
            return None

    if backup:
        if run("backup", lambda: str(backup_database(schema.DB_PATH, backup_dir))) is None:
            report["problems"].append("nothing else was run: without a backup the data is not touched")
            return _finish(report)

    conn = schema.get_connection()
    try:
        report["rows_before"] = table_counts(conn)
        if online:
            synced = run("sync", lambda: sync_until_complete(conn, steps["sync_all"], steps["audit"]))
            if synced and not (synced["votes_complete"] and synced["forum_complete"]):
                report["warnings"].append(
                    f"data is not complete after {synced['rounds']} sync round(s) ({synced['stopped_because']}): "
                    f"{len(synced['incomplete']['proposals'])} proposal(s) without all votes, "
                    f"{len(synced['incomplete']['threads'])} forum thread(s) not fully fetched")
        identity = run("identity", lambda: steps["rescore"](conn))
        if identity:
            report["steps"]["identity"] = identity.get("stats", identity)      # the steps list is long
        index = run("index", lambda: steps["sync_index"](conn))
        if index and index.get("foreign"):
            report["warnings"].append(f"{index['foreign']} document(s) in the index were not created by this "
                                      f"pipeline: {index.get('foreign_ids')}")
        report["rows_after"] = table_counts(conn)
    finally:
        conn.close()

    checked = run("check", steps["check_index"])
    if checked and checked.get("invalid"):
        report["problems"].append(f"{checked['invalid']} chunk(s) in the index have invalid metadata")
    if checked and checked.get("legacy"):
        report["warnings"].append(f"{checked['legacy']} chunk(s) still have the old metadata format")

    for table, before in report["rows_before"].items():
        after = report["rows_after"][table]
        if after < before * (1 - MAX_SHRINK):
            report["problems"].append(f"{table} shrank from {before} to {after} rows")
    return _finish(report)


def _finish(report: dict) -> dict:
    report["ok"] = not report["problems"]
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return report


def main(argv=None, log_dir: Path = LOG_DIR) -> int:
    """The command line: lock, log file, refresh(), logs/last_refresh.json. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Backup, data sync, identity re-check, index sync, index check")
    parser.add_argument("--no-backup", action="store_true", help="Skip the database backup")
    parser.add_argument("--offline", action="store_true", help="Skip the network sync")
    args = parser.parse_args(argv)

    lock = acquire_lock(log_dir)
    if lock is None:
        print(f"Another refresh is running ({log_dir / LOCK_NAME}). Nothing done.")
        return 2
    try:
        log_file = log_dir / f"refresh_{_stamp()}.log"
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True,
                            handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()])
        report = refresh(backup=not args.no_backup, online=not args.offline)
        report["log_file"] = str(log_file)
        (log_dir / REPORT_NAME).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        for old in sorted(log_dir.glob("refresh_*.log"))[:-KEEP_LOGS]:
            old.unlink()
        logger.info("REFRESH %s  problems=%s  warnings=%s", "OK" if report["ok"] else "FAILED",
                    report["problems"], report["warnings"])
        return 0 if report["ok"] else 1
    finally:
        logging.shutdown()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())


# ── Where control goes next ───────────────────────────────────────────────────
# The program ends. To see how the last run went: logs/last_refresh.json ("ok", "problems",
#   "warnings", row counts before and after) and the log file it names.
# If it reports problems: the database backup taken at the start of that run is in backups/
#   (see TO RESTORE A BACKUP above).
# If the data stays incomplete run after run: python -m features.sync.runner --check lists
#   which proposals or threads are missing and why.
