from ingestion.snapshot_client import get_space, get_proposals   
from db.schema import get_connection    
from datetime import datetime, timezone    
from config.curated_daos import CURATED_DAOS        
from json import dumps as json_dumps              

''' we are not using the snapshot client for votes because it is too slow and we can get them from the API directly 
 so we will use optemised concepts and use lasy loading and timeout requests to get the votes from the API directly and then we will use the snapshot client to get the proposals and spaces '''

def ingest_space(space_id: str, conn):
    space = get_space(space_id)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO spaces (id, name, about, network, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            about=excluded.about,
            network=excluded.network,
            fetched_at=excluded.fetched_at
        """,
        (space["id"], space["name"], space["about"], space["network"], now)
    )
    conn.commit()


def ingest_proposals_for_space(space_id: str, conn, first: int = 20):
    proposals = get_proposals(space_id, first=first)
    now = datetime.now(timezone.utc).isoformat()

    for p in proposals:
        conn.execute(
            """
            INSERT INTO proposals
                (id, space_id, title, body, choices_json, state, votes_count,
                 scores_json, scores_total, start_ts, end_ts, link,
                 discussion_url, author, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                body=excluded.body,
                state=excluded.state,
                votes_count=excluded.votes_count,
                scores_json=excluded.scores_json,
                scores_total=excluded.scores_total,
                fetched_at=excluded.fetched_at
            """,
            (
                p["id"], space_id, p["title"], p["body"],
                json_dumps(p["choices"]), p["state"], p["votes"],
                json_dumps(p["scores"]), p["scores_total"],
                p["start"], p["end"], p["link"], p.get("discussion"),
                p["author"], now,
            ),
        )
    conn.commit()
    print(f"    {len(proposals)} proposals ingested for {space_id}")


if __name__ == "__main__":
    conn = get_connection()

    for dao in CURATED_DAOS:
        print(f"Ingesting: {dao['name']}...")
        ingest_space(dao["id"], conn)
        ingest_proposals_for_space(dao["id"], conn)

    conn.close()
    print("Done.")