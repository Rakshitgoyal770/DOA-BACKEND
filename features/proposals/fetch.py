# features/proposals/fetch.py
"""Pull new/updated proposals from Snapshot for every curated DAO."""

import datetime
import json
import logging
from typing import Dict

from clients.snapshot import get_proposals
from config.curated_daos import CURATED_DAOS

logger = logging.getLogger(__name__)


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
