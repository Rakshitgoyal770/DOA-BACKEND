# vector/embedding.py
"""
Keeps the ChromaDB search index in step with SQLite, touching only what changed.

What goes into the index (each item is a "document"):
  * proposal body chunks   id: proposal_<proposal_id>_<n>
  * forum posts            id: forum_post_<proposal_id>_<post_id>
                           (a post is stored once per proposal linking its thread)

For every document, a sync compares SQLite (what it should be) with Chroma
(what it is) and picks the cheapest correct action:

    new id, or text changed   -> embed the text (the slow part) and save it
    same text, new metadata   -> update the metadata only (no embedding)
    nothing changed           -> skip
    id no longer in SQLite    -> delete it from the index

So a normal run after a sync embeds only the handful of new posts, and an
identity change (e.g. a newly linked wallet) is a cheap metadata update.

Run:
    python -m vector.embedding            # sync the index
    python -m vector.embedding --dry-run  # only report what would change
"""

import argparse
import math
from functools import lru_cache
from pathlib import Path

from vector.chunking import chunk_proposal_body

MODEL_NAME = "BAAI/bge-small-en-v1.5"
CHROMA_PATH = Path(__file__).resolve().parent.parent / "chroma_data"
COLLECTION_NAME = "dao_chunks"

ENCODE_BATCH_SIZE = 64     # texts per model.encode call
WRITE_BATCH_SIZE = 256     # documents per Chroma write (Chroma rejects very large batches)
OUR_ID_PREFIXES = ("proposal_", "forum_post_")   # we only ever delete ids we created


# ── Model and collection (loaded on first use, then reused) ──────────────────

@lru_cache(maxsize=1)
def get_model():
    """The embedding model. Loading takes seconds, so it happens only when needed."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def get_collection():
    """The persistent Chroma collection holding all documents."""
    import chromadb
    return chromadb.PersistentClient(path=str(CHROMA_PATH)).get_or_create_collection(name=COLLECTION_NAME)


# ── What the index SHOULD contain, built from SQLite ─────────────────────────

def proposal_documents(conn) -> dict[str, tuple[str, dict]]:
    """{doc_id: (text, metadata)} for every chunk of every proposal body."""
    docs = {}
    for p in conn.execute("SELECT id, space_id, title, body FROM proposals"):
        for i, text in enumerate(chunk_proposal_body(p["body"])):
            docs[f"proposal_{p['id']}_{i}"] = (text, {
                "source_type": "proposal_body",
                "proposal_id": p["id"],
                "space_id": p["space_id"],
                "title": p["title"],
            })
    return docs


def forum_documents(conn) -> dict[str, tuple[str, dict]]:
    """
    {doc_id: (text, metadata)} for every non-empty forum post.

    If the author is linked to a wallet, the metadata also carries the wallet,
    the link confidence, and the wallet's voting power on THIS proposal.
    Wallets are compared lower-case: Snapshot writes them in mixed case.
    """
    rows = conn.execute("""
        SELECT f.id, f.proposal_id, f.username, f.content,
               r.wallet_address, r.confidence_level, v.vp
        FROM forum_posts f
        LEFT JOIN resolved_identities r ON r.forum_username = lower(f.username)
        LEFT JOIN votes v ON v.proposal_id = f.proposal_id
                         AND lower(v.voter) = lower(r.wallet_address)
        WHERE f.content IS NOT NULL AND f.content != ''
    """)
    docs = {}
    for r in rows:
        metadata = {"source_type": "forum_post", "proposal_id": r["proposal_id"], "author": r["username"]}
        # Chroma does not accept None values, so a field is left out rather than set to null.
        if r["wallet_address"]:
            metadata["resolved_wallet"] = r["wallet_address"]
            metadata["confidence_level"] = r["confidence_level"]
        if r["vp"] is not None:
            metadata["voting_power"] = r["vp"]
        docs[f"forum_post_{r['proposal_id']}_{r['id']}"] = (r["content"], metadata)
    return docs


# ── What the index DOES contain ──────────────────────────────────────────────

def indexed_documents(collection, page_size: int = 1000) -> dict[str, tuple[str, dict]]:
    """{doc_id: (text, metadata)} currently stored in Chroma, read page by page."""
    docs, offset = {}, 0
    while True:
        page = collection.get(include=["documents", "metadatas"], limit=page_size, offset=offset)
        for doc_id, text, metadata in zip(page["ids"], page["documents"], page["metadatas"]):
            docs[doc_id] = (text, metadata or {})
        if len(page["ids"]) < page_size:
            return docs
        offset += page_size


# ── Compare and apply ────────────────────────────────────────────────────────

def same_metadata(a: dict, b: dict) -> bool:
    """
    True if two metadata dicts hold the same values.

    Floats are compared with a tiny tolerance: Chroma hands back e.g.
    95848.83524269491 for a stored 95848.83524269493, and a plain `==` would
    treat that as a change and rewrite the document on every sync.
    """
    if a.keys() != b.keys():
        return False
    for key, x in a.items():
        y = b[key]
        if isinstance(x, float) or isinstance(y, float):
            if not math.isclose(x, y, rel_tol=1e-9):
                return False
        elif x != y:
            return False
    return True


def plan_changes(wanted: dict, current: dict) -> dict[str, list[str]]:
    """Sort every document id into embed / update_metadata / delete / unchanged."""
    plan = {"embed": [], "update_metadata": [], "delete": [], "unchanged": []}
    for doc_id, (text, metadata) in wanted.items():
        if doc_id not in current or current[doc_id][0] != text:
            plan["embed"].append(doc_id)
        elif not same_metadata(current[doc_id][1], metadata):
            plan["update_metadata"].append(doc_id)
        else:
            plan["unchanged"].append(doc_id)
    plan["delete"] = [doc_id for doc_id in current
                      if doc_id not in wanted and doc_id.startswith(OUR_ID_PREFIXES)]
    return plan


def metadata_patch(old: dict | None, new: dict) -> dict:
    """
    The metadata to send so Chroma ends up storing exactly `new`.

    Chroma MERGES metadata on update/upsert: a key we leave out is kept. So when
    a field should disappear (e.g. a wallet link was removed), we must send it
    as None, which tells Chroma to delete that key.
    """
    patch = dict(new)
    for key in old or {}:
        if key not in new:
            patch[key] = None
    return patch


def _batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def sync_index(conn, collection=None, model=None, dry_run: bool = False) -> dict:
    """
    Bring the Chroma index in line with SQLite. Returns how many documents
    were embedded, had metadata updated, were deleted, or were unchanged.

    `collection` and `model` default to the real ones; tests pass small fakes.
    The model is only loaded if something actually needs embedding.
    """
    collection = collection if collection is not None else get_collection()
    wanted = {**proposal_documents(conn), **forum_documents(conn)}
    current = indexed_documents(collection)
    plan = plan_changes(wanted, current)

    def metadatas_for(ids):
        return [metadata_patch(current[i][1] if i in current else None, wanted[i][1]) for i in ids]

    if not dry_run:
        if plan["embed"]:
            model = model if model is not None else get_model()
            for ids in _batches(plan["embed"], WRITE_BATCH_SIZE):
                texts = [wanted[i][0] for i in ids]
                vectors = model.encode(texts, batch_size=ENCODE_BATCH_SIZE)
                collection.upsert(
                    ids=ids,
                    documents=texts,
                    embeddings=[[float(x) for x in v] for v in vectors],
                    metadatas=metadatas_for(ids),
                )
        for ids in _batches(plan["update_metadata"], WRITE_BATCH_SIZE):
            collection.update(ids=ids, metadatas=metadatas_for(ids))
        for ids in _batches(plan["delete"], WRITE_BATCH_SIZE):
            collection.delete(ids=ids)

    return {"dry_run": dry_run, "documents": len(wanted),
            **{action: len(ids) for action, ids in plan.items()}}


if __name__ == "__main__":
    from db.schema import get_connection

    parser = argparse.ArgumentParser(description="Sync the ChromaDB index with SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    args = parser.parse_args()

    conn = get_connection()
    print(sync_index(conn, dry_run=args.dry_run))
    conn.close()
