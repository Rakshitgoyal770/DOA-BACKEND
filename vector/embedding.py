from datetime import datetime, timezone

from sentence_transformers import SentenceTransformer
import chromadb

from vector.chunking import chunk_proposal_body

from db.schema import get_connection



model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.get_or_create_collection(name="dao_chunks")




def embed_proposals(conn):
    proposals = conn.execute("SELECT id, space_id, title, body FROM proposals").fetchall()
    count = 0

    for p in proposals:
        chunks = chunk_proposal_body(p["body"])
        for i, chunk_text in enumerate(chunks):
            chunk_id = f"proposal_{p['id']}_{i}"
            embedding = model.encode(chunk_text).tolist()

            collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk_text],
                metadatas=[{
                    "source_type": "proposal_body",
                    "proposal_id": p["id"],
                    "space_id": p["space_id"],
                    "title": p["title"],
                }]
            )
            count += 1

    print(f"Embedded {count} proposal chunks")


def embed_forum_posts(conn):
    posts = conn.execute(
        "SELECT id, proposal_id, username, content FROM forum_posts"
    ).fetchall()
    count = 0

    for post in posts:
        if not post["content"]:
            continue

        # Look up resolved identity for this forum username
        identity = conn.execute(
            "SELECT wallet_address, confidence_level FROM resolved_identities WHERE forum_username = ?",
            (post["username"].lower(),)
        ).fetchone()

        voting_power = None
        wallet_address = None
        confidence_level = None

        if identity:
            wallet_address = identity["wallet_address"]
            confidence_level = identity["confidence_level"]

            # Look up their actual vote power on THIS specific proposal
            vote_row = conn.execute(
                "SELECT vp FROM votes WHERE proposal_id = ? AND voter = ?",
                (post["proposal_id"], wallet_address)
            ).fetchone()

            if vote_row:
                voting_power = vote_row["vp"]

        chunk_id = f"forum_post_{post['id']}"
        embedding = model.encode(post["content"]).tolist()

        metadata = {
            "source_type": "forum_post",
            "proposal_id": post["proposal_id"],
            "author": post["username"],
        }
        # Only add these fields if they have real values —
        # ChromaDB metadata doesn't handle None well, so omit rather than null
        if wallet_address:
            metadata["resolved_wallet"] = wallet_address
            metadata["confidence_level"] = confidence_level
        if voting_power is not None:
            metadata["voting_power"] = voting_power

        collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[post["content"]],
            metadatas=[metadata]
        )
        count += 1

    print(f"Embedded {count} forum post chunks")


if __name__ == "__main__":
    conn = get_connection()
    embed_proposals(conn)
    embed_forum_posts(conn)
    conn.close()
    print("Done.")