from datetime import datetime, timezone

from sentence_transformers import SentenceTransformer
import chromadb

from db.schema import get_connection

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.get_or_create_collection(name="dao_chunks")


def chunk_proposal_body(body: str, max_chars: int = 1500) -> list[str]:
    if not body:
        return []
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    chunks = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) < max_chars:
            current += ("\n\n" + p if current else p)
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


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
        chunk_id = f"forum_post_{post['id']}"
        embedding = model.encode(post["content"]).tolist()

        collection.upsert(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[post["content"]],
            metadatas=[{
                "source_type": "forum_post",
                "proposal_id": post["proposal_id"],
                "author": post["username"],
            }]
        )
        count += 1

    print(f"Embedded {count} forum post chunks")


if __name__ == "__main__":
    conn = get_connection()
    embed_proposals(conn)
    embed_forum_posts(conn)
    conn.close()
    print("Done.")