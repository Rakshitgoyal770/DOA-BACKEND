# ingestion/ingest_votes.py
from datetime import datetime, timezone
from json import dumps as json_dumps
from config.curated_daos import CURATED_DAOS

from ingestion.snapshot_client import get_votes
from db.schema import get_connection


def ingest_votes_for_proposal(proposal_id: str, conn, first: int = 1000):
    votes = get_votes(proposal_id, first=first)
    now = datetime.now(timezone.utc).isoformat()

    for v in votes:
        vote_key = f"{proposal_id}_{v['voter']}"
        conn.execute(
            """
            INSERT INTO votes (vote_key, proposal_id, voter, choice_json, vp, created_ts, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vote_key) DO UPDATE SET
                choice_json=excluded.choice_json,
                vp=excluded.vp,
                fetched_at=excluded.fetched_at
            """,
            (vote_key, proposal_id, v["voter"], json_dumps(v["choice"]), v["vp"], v["created"], now),
        )

    conn.commit()
    print(f"    {len(votes)} votes ingested for proposal {proposal_id}")
    return len(votes)

if __name__ == "__main__":
    conn = get_connection()
    ingest_votes_for_proposal(
        "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
        conn
    )
    conn.close()