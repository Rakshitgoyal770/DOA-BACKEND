# vector/embedding.py
"""
vector/embedding.py — Keeps the ChromaDB search index in step with SQLite, touching only what changed.

What goes into the index (each item is a "document"):
  * proposal body chunks   id: proposal_<proposal_id>_<n>
  * forum posts            id: forum_post_<proposal_id>_<post_id>
                           (a post is stored once per proposal linking its thread).
                           A post too long for one chunk is split (vector/chunking.py)
                           and its chunks get ids forum_post_<proposal_id>_<post_id>_c<n>.

For every document, a sync compares SQLite (what it should be) with Chroma
(what it is) and picks the cheapest correct action:

    new id, text changed, or its context line changed
                              -> embed it (the slow part) and save it.  What is embedded is a
                                 context line + the chunk ("Forum post by <author> on the proposal
                                 "<title>":"), see embedding_text; the stored document is the chunk.
    same text, new metadata   -> update the metadata only (no embedding)
    nothing changed           -> skip
    id no longer in SQLite    -> delete it from the index

So a normal run after a sync embeds only the handful of new posts, and an
identity change (e.g. a newly linked wallet) is a cheap metadata update.

WHERE IT SITS
    SQLite (proposals, forum_posts, identities, votes) --> THIS FILE --> ChromaDB (chroma_data/)
    Read back at question time by features/chat/retrieval.py (get_model, get_collection).

Every chunk's metadata is built through vector/chunk_metadata.py (one validated schema:
DAO, proposal, thread, post, author, dates, chunk position, content hash).

Run (after a data sync and the identity re-check):
    python -m vector.embedding                   # sync the index
    python -m vector.embedding --dry-run         # only report what would change
    python -m vector.embedding --check           # validate every stored chunk's metadata (no model, no writes)
    python -m vector.embedding --remove-foreign  # also delete ids this pipeline did not create (reported as "foreign")
"""

import argparse
import math
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from vector.chunk_metadata import (MANAGED_BY, ChunkMetadata, content_hash, epoch_from_iso,
                                   thread_key)
from vector.chunking import FORUM_MAX_CHARS, PROPOSAL_MAX_CHARS, chunk_text

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# bge models are trained to receive this instruction in front of a QUESTION (never in front of
# a document). Measured on eval/retrieval_set.json: with it, top-5 hits rose from 67% to 77%.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL_MAX_TOKENS = 510     # the model reads 512 tokens, 2 of them are its own start/end marks
HEADER_TITLE_WORDS = 8     # a title is cut to this many words when the full context line does not fit
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


# ── What is embedded: a context line + the chunk ─────────────────────────────

def context_header(source_type: str, title: str | None, author: str | None = None) -> str:
    """
    The line put in front of a chunk before it is embedded, e.g.
    'Forum post by kpk on the proposal "GLI - Incentivized Delegation Vaults":'.

    Why: a chunk is a slice of a post. On its own it does not say who wrote it or which
    proposal it is about, so a question naming the person or the proposal had nothing to
    match (measured: such questions found their passage in the top 5 only 33% of the time).
    The stored document stays the plain chunk; only the embedding (and the keyword index)
    see this line.
    """
    about = f' the proposal "{title.strip()}"' if title and title.strip() else " a proposal"
    if source_type == "forum_post":
        return f"Forum post by {author or 'unknown'} on{about}:\n"
    return f"Text of{about}:\n"


def embedding_text(text: str, metadata: dict, count_tokens=None) -> str:
    """
    The exact text that is embedded for one chunk: context_header + the chunk.

    The result must fit the model: a text over its token limit is not cut by the model, the
    embedding call fails. So when the full line does not fit, the title is shortened (to
    HEADER_TITLE_WORDS words), then dropped, and for a chunk that fills the limit on its own
    the chunk is embedded without any line. The chunk's own words always stay whole.

    Parameters (where they come from):
        text         - the chunk.
        metadata     - its metadata (source_type, title, author), as built below or as stored.
        count_tokens - token_counter(model); None (tests' fake models) = never shorten.
    """
    kind, title, author = metadata.get("source_type"), metadata.get("title"), metadata.get("author")
    full = context_header(kind, title, author) + text
    if count_tokens is None or count_tokens(full) <= MODEL_MAX_TOKENS:
        return full
    words = (title or "").split()
    if len(words) > HEADER_TITLE_WORDS:
        shorter = context_header(kind, " ".join(words[:HEADER_TITLE_WORDS]) + " ...", author) + text
        if count_tokens(shorter) <= MODEL_MAX_TOKENS:
            return shorter
    without_title = context_header(kind, None, author) + text
    return without_title if count_tokens(without_title) <= MODEL_MAX_TOKENS else text


def encode_query(model, question: str) -> list[float]:
    """A question as a vector, with the instruction the model expects in front of questions."""
    return [float(x) for x in model.encode(QUERY_PREFIX + question)]


def _stamp_embedded(text: str, metadata: dict, count_tokens) -> dict:
    """The metadata plus embedded_hash (the hash of what will be embedded for this chunk)."""
    return {**metadata, "embedded_hash": content_hash(embedding_text(text, metadata, count_tokens))}


# ── What the index SHOULD contain, built from SQLite ─────────────────────────

def token_counter(model):
    """
    The model's tokenizer as a function text -> number of tokens, or None if the model
    has no tokenizer (the small fakes used in tests; chunking then uses characters only).

    Parameter (where it comes from):
        model - the embedding model (get_model(), or a test's fake), from sync_index().
    """
    tokenizer = getattr(model, "tokenizer", None)
    if tokenizer is None:
        return None
    tokenizer.model_max_length = 10 ** 9          # we measure long texts on purpose; silence the warning
    return lambda text: len(tokenizer(text, add_special_tokens=False)["input_ids"])


def proposal_documents(conn, count_tokens=None) -> dict[str, tuple[str, dict]]:
    """
    {doc_id: (text, metadata)} for every chunk of every proposal body
    (chunks of at most PROPOSAL_MAX_CHARS characters, see vector/chunking.py).

    Parameters (where they come from — sync_index):
        conn         - the open SQLite connection.
        count_tokens - token_counter(model), so chunks also respect the token limit.
    """
    docs = {}
    for p in conn.execute("SELECT id, space_id, title, body, created_ts, author FROM proposals"):
        chunks = chunk_text(p["body"], PROPOSAL_MAX_CHARS, count_tokens)
        for i, text in enumerate(chunks):
            docs[f"proposal_{p['id']}_{i}"] = (text, _stamp_embedded(text, ChunkMetadata(
                source_type="proposal_body",
                proposal_id=p["id"],
                space_id=p["space_id"] or None,
                title=p["title"] or None,
                chunk_index=i,
                chunk_count=len(chunks),
                content_hash=content_hash(text),
                created_at=p["created_ts"],
                proposal_author=(p["author"] or "").lower() or None,
            ).to_chroma(), count_tokens))
    return docs


def forum_documents(conn, count_tokens=None) -> dict[str, tuple[str, dict]]:
    """
    {doc_id: (text, metadata)} for every non-empty forum post. A post that fits in one
    chunk (FORUM_MAX_CHARS) keeps the id forum_post_<proposal_id>_<post_id>; a longer one
    becomes several documents ending _c0, _c1, ..., all carrying the same metadata.

    If the author is linked to a wallet, the metadata also carries the wallet,
    the link confidence, and the wallet's voting power on THIS proposal.
    Wallets are compared lower-case: Snapshot writes them in mixed case.

    Parameters (where they come from — sync_index): conn, and count_tokens as in
    proposal_documents.
    """
    rows = conn.execute("""
        SELECT f.id, f.proposal_id, f.topic_id, f.post_number, f.username, f.content, f.created_at,
               r.wallet_address, r.confidence_level, v.vp,
               p.space_id, p.title, p.discussion_url
        FROM forum_posts f
        LEFT JOIN proposals p ON p.id = f.proposal_id
        LEFT JOIN resolved_identities r ON r.forum_username = lower(f.username)
        LEFT JOIN votes v ON v.proposal_id = f.proposal_id
                         AND lower(v.voter) = lower(r.wallet_address)
        WHERE f.content IS NOT NULL AND f.content != ''
    """)
    docs = {}
    for r in rows:
        base_id = f"forum_post_{r['proposal_id']}_{r['id']}"
        chunks = chunk_text(r["content"], FORUM_MAX_CHARS, count_tokens)
        for i, text in enumerate(chunks):
            # None fields are dropped by to_chroma(): Chroma does not accept null values.
            docs[base_id if len(chunks) == 1 else f"{base_id}_c{i}"] = (text, _stamp_embedded(text, ChunkMetadata(
                source_type="forum_post",
                proposal_id=r["proposal_id"],
                space_id=r["space_id"] or None,
                title=r["title"] or None,
                chunk_index=i,
                chunk_count=len(chunks),
                content_hash=content_hash(text),
                created_at=epoch_from_iso(r["created_at"]),
                author=r["username"] or None,
                author_lower=(r["username"] or "").lower() or None,
                post_id=r["id"],
                post_number=r["post_number"],
                topic_id=r["topic_id"],
                thread_key=thread_key(r["discussion_url"], r["topic_id"]),
                resolved_wallet=r["wallet_address"] or None,
                confidence_level=r["confidence_level"] if r["wallet_address"] else None,
                voting_power=r["vp"],
            ).to_chroma(), count_tokens))
    return docs


# ── What the index DOES contain ──────────────────────────────────────────────

def indexed_documents(collection, page_size: int = 1000) -> dict[str, tuple[str, dict]]:
    """
    {doc_id: (text, metadata)} currently stored in Chroma, read page by page.

    Parameters (where they come from):
        collection - from sync_index() (the real one, or a test's in-memory one).
        page_size  - documents read per request.
    """
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

    Parameters (where they come from): the stored and the wanted metadata of one
    document, from plan_changes().
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
    """
    Sort every document id into embed / update_metadata / delete / unchanged, plus "foreign".

    A document in Chroma that SQLite no longer wants is deleted only if this pipeline
    created it: its id has one of our prefixes, or it carries our managed_by stamp.
    Anything else is "foreign" (for example a document added by hand): it is reported
    and left alone, and only removed when the caller asks (sync_index remove_foreign).

    Parameters (where they come from — sync_index):
        wanted  - proposal_documents() + forum_documents(): what SQLite says should exist.
        current - indexed_documents(): what Chroma holds now.
    """
    plan = {"embed": [], "update_metadata": [], "delete": [], "unchanged": [], "foreign": []}
    for doc_id, (text, metadata) in wanted.items():
        if (doc_id not in current or current[doc_id][0] != text
                or current[doc_id][1].get("embedded_hash") != metadata.get("embedded_hash")):
            plan["embed"].append(doc_id)                  # new, edited, or its context line changed
        elif not same_metadata(current[doc_id][1], metadata):
            plan["update_metadata"].append(doc_id)
        else:
            plan["unchanged"].append(doc_id)
    for doc_id, (_text, metadata) in current.items():
        if doc_id in wanted:
            continue
        ours = doc_id.startswith(OUR_ID_PREFIXES) or metadata.get("managed_by") == MANAGED_BY
        plan["delete" if ours else "foreign"].append(doc_id)
    return plan


def metadata_patch(old: dict | None, new: dict) -> dict:
    """
    The metadata to send so Chroma ends up storing exactly `new`.

    Chroma MERGES metadata on update/upsert: a key we leave out is kept. So when
    a field should disappear (e.g. a wallet link was removed), we must send it
    as None, which tells Chroma to delete that key.

    Parameters (where they come from): the document's stored metadata (None for a
    new document) and its wanted metadata, from sync_index().
    """
    patch = dict(new)
    for key in old or {}:
        if key not in new:
            patch[key] = None
    return patch


def _batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def sync_index(conn, collection=None, model=None, dry_run: bool = False, remove_foreign: bool = False) -> dict:
    """
    Bring the Chroma index in line with SQLite. Returns how many documents
    were embedded, had metadata updated, were deleted, or were unchanged, and how many
    "foreign" documents (ids this pipeline did not create) were found. Their ids (up to 20)
    are in "foreign_ids"; they are deleted only with remove_foreign=True, and then counted
    under "delete" as well.

    `collection` and `model` default to the real ones; tests pass small fakes.
    The model is always loaded, because its tokenizer sets how large chunks may be
    (a fake without a tokenizer means characters-only limits).

    Parameters (where they come from):
        conn           - opened by the command line below.
        collection     - None = the real index (get_collection); tests pass an in-memory one.
        model          - None = the real model (get_model); tests pass a fake.
        dry_run        - the --dry-run flag: report the plan, write nothing.
        remove_foreign - the --remove-foreign flag: also delete the foreign documents.
    """
    collection = collection if collection is not None else get_collection()
    model = model if model is not None else get_model()
    count_tokens = token_counter(model)
    wanted = {**proposal_documents(conn, count_tokens), **forum_documents(conn, count_tokens)}
    current = indexed_documents(collection)
    plan = plan_changes(wanted, current)
    foreign = list(plan["foreign"])
    if remove_foreign:
        plan["delete"] = plan["delete"] + foreign

    def metadatas_for(ids):
        return [metadata_patch(current[i][1] if i in current else None, wanted[i][1]) for i in ids]

    if not dry_run:
        if plan["embed"]:
            for ids in _batches(plan["embed"], WRITE_BATCH_SIZE):
                texts = [wanted[i][0] for i in ids]                       # stored: the plain chunk
                embedded = [embedding_text(wanted[i][0], wanted[i][1], count_tokens) for i in ids]
                vectors = model.encode(embedded, batch_size=ENCODE_BATCH_SIZE)
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
            **{action: len(ids) for action, ids in plan.items()},
            "foreign_ids": foreign[:20]}


# ── Checking what is stored ───────────────────────────────────────────────────

def check_index(collection) -> dict:
    """
    Validate the metadata of every stored chunk against vector/chunk_metadata.py. No model, no writes.

    Returns:
        total          - chunks in the collection
        valid          - stamped chunks whose metadata passes the schema
        invalid        - stamped chunks that do not (up to 10 examples under "invalid_examples")
        legacy         - our ids (proposal_ / forum_post_) without the managed_by stamp: they
                         need a sync to be updated
        foreign        - everything else (ids this pipeline did not create), up to 20 under "foreign_ids"

    Parameter (where it comes from): the real index (get_collection) or a test's collection.
    """
    out = {"total": 0, "valid": 0, "invalid": 0, "legacy": 0, "foreign": 0,
           "invalid_examples": [], "foreign_ids": []}
    for doc_id, (_text, metadata) in indexed_documents(collection).items():
        out["total"] += 1
        if metadata.get("managed_by") == MANAGED_BY:
            try:
                ChunkMetadata(**metadata)
                out["valid"] += 1
            except (ValidationError, TypeError) as error:
                out["invalid"] += 1
                if len(out["invalid_examples"]) < 10:
                    out["invalid_examples"].append({"id": doc_id, "error": str(error).splitlines()[0]})
        elif doc_id.startswith(OUR_ID_PREFIXES):
            out["legacy"] += 1
        else:
            out["foreign"] += 1
            if len(out["foreign_ids"]) < 20:
                out["foreign_ids"].append(doc_id)
    return out


if __name__ == "__main__":
    import sys

    from db.schema import get_connection

    parser = argparse.ArgumentParser(description="Sync the ChromaDB index with SQLite")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    parser.add_argument("--check", action="store_true",
                        help="Validate every stored chunk's metadata; no model, no writes")
    parser.add_argument("--remove-foreign", action="store_true",
                        help="Also delete documents this pipeline did not create (they are always reported)")
    args = parser.parse_args()

    if args.check:
        report = check_index(get_collection())
        print(report)
        sys.exit(1 if report["invalid"] else 0)

    conn = get_connection()
    print(sync_index(conn, dry_run=args.dry_run, remove_foreign=args.remove_foreign))
    conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# From the command line: the counts are printed and the program ends.
# The index is read at question time by features/chat/retrieval.py.
# If you change the model, chunk size or document ids: the next sync re-embeds
#   everything affected (a few minutes on CPU); run with --dry-run first to see how much.
