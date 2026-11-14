# features/chat/retrieval.py
"""
features/chat/retrieval.py — Finds the text chunks that best answer a question: meaning AND keywords.

WHAT THIS FILE DOES
    retrieve() runs two searches over the same chunks and merges them:
        1. vector search   the question is embedded with the same model as the documents
                           (vector/embedding.py) and ChromaDB returns the nearest chunks:
                           good at meaning, weak at exact words
        2. keyword search  BM25 (vector/keyword_index.py): good at exact words (a username,
                           a ticker, a proposal number), blind to meaning
        3. merge           reciprocal rank fusion: a chunk scores 1/(60 + its rank) in each
                           list it appears in, and the scores are added. A chunk both searches
                           rank high comes first; no score of one search has to be compared
                           with a score of the other.
        4. rerank          the best CANDIDATES of the merged list are re-ordered by a model that
                           reads the question and each passage together (vector/reranker.py)
    Chunks whose vector distance is above `max_distance` are dropped before the rerank (a chunk
    that only shares a common word with the question is not evidence), and the best
    `n_results` are returned.

    Measured on eval/retrieval_set.json: run `python -m eval.retrieval_eval` (no LLM calls).

WHERE IT SITS
    features/chat/tools.py search_forum()
        --> THIS FILE --> vector/embedding.py (model, collection) and vector/keyword_index.py
"""

from vector.embedding import embedding_text, encode_query, get_collection, get_model
from vector.keyword_index import get_keyword_index
from vector.reranker import rerank

CANDIDATES = 30      # chunks taken from each search before merging
RRF_K = 60           # the constant of reciprocal rank fusion (the usual value)


def fuse(ranked_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """
    Reciprocal rank fusion: {chunk_id: score}, where each list adds 1 / (k + rank) for the
    chunks it contains (rank 1 = first). Higher is better.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _squared_distance(a, b) -> float:
    """The distance Chroma reports for this collection (squared L2), for a chunk only the keyword search found."""
    return float(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def retrieve(query: str, n_results: int = 5, where: dict = None, max_distance: float = 0.7,
             collection=None, model=None, keyword_index=None, reranker=None):
    """
    The best chunks for a question, best first:
    [{"id", "document", "metadata", "distance", "score", "found_by", "rerank_score"}].
        distance     - vector distance to the question (lower = closer in meaning)
        score        - the merged rank score of the two searches (higher = better)
        rerank_score - the reranker's score (higher = better); what the list is ordered by.
                       Missing when the reranker is off or could not be loaded: the list is
                       then ordered by score.
        found_by     - ["vector"], ["keyword"] or both
    An empty list means nothing was close enough.

    Parameters (where they come from — features/chat/tools.py search_forum):
        query        - the search sentence.
        n_results    - how many chunks to return (after merging and the distance cutoff).
        where        - a Chroma filter ({"proposal_id": ...}, {"$and": [...]}, ...) or None;
                       applied to both searches.
        max_distance - chunks further than this from the question are dropped.
        collection, model, keyword_index - None = the real ones; tests pass fakes.
        reranker     - None = the real one (vector/reranker.py); False = no reranking;
                       or anything with predict(pairs) (tests).
    """
    collection = collection if collection is not None else get_collection()
    model = model if model is not None else get_model()
    keyword_index = keyword_index if keyword_index is not None else get_keyword_index(collection)

    query_vector = encode_query(model, query)
    found = collection.query(query_embeddings=[query_vector], n_results=CANDIDATES, where=where)
    chunks = {}
    vector_ids = []
    for chunk_id, doc, meta, dist in zip(found["ids"][0], found["documents"][0],
                                         found["metadatas"][0], found["distances"][0]):
        vector_ids.append(chunk_id)
        chunks[chunk_id] = {"id": chunk_id, "document": doc, "metadata": meta, "distance": dist,
                            "found_by": ["vector"]}

    keyword_hits = keyword_index.search(query, n=CANDIDATES, where=where)
    keyword_only = [h["id"] for h in keyword_hits if h["id"] not in chunks]
    if keyword_only:                                  # their distance was not part of the vector result
        stored = collection.get(ids=keyword_only, include=["embeddings"])
        vectors = dict(zip(stored["ids"], stored["embeddings"]))
    for hit in keyword_hits:
        if hit["id"] in chunks:
            chunks[hit["id"]]["found_by"].append("keyword")
        elif hit["id"] in vectors:                    # (a chunk deleted since the keyword index was built is skipped)
            chunks[hit["id"]] = {"id": hit["id"], "document": hit["document"], "metadata": hit["metadata"],
                                 "distance": _squared_distance(query_vector, vectors[hit["id"]]),
                                 "found_by": ["keyword"]}

    scores = fuse([vector_ids, [h["id"] for h in keyword_hits if h["id"] in chunks]])
    ranked = sorted(chunks.values(), key=lambda c: (-scores[c["id"]], c["distance"]))
    candidates = []
    for chunk in ranked:
        if chunk["distance"] <= max_distance:
            chunk["score"] = scores[chunk["id"]]
            candidates.append(chunk)
            if len(candidates) == CANDIDATES:
                break
    if reranker is not False:
        # the reranker reads the same text that was embedded: the context line + the chunk
        candidates = rerank(query, candidates, model=reranker,
                            text_of=lambda c: embedding_text(c["document"], c["metadata"]))
    return candidates[:n_results]


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/tools.py search_forum(), which adds each author's wallet and
#   vote (context.enrich_chunks) and the proposal title.
# If the index is empty or out of date: run python -m vector.embedding.
# First call in a process loads the embedding model and builds the keyword index (a few seconds).
# To measure a change here: python -m eval.retrieval_eval (no LLM calls).
