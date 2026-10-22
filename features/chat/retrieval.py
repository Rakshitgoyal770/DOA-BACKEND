# features/chat/retrieval.py
"""
features/chat/retrieval.py — Finds the text chunks closest in meaning to a question.

WHAT THIS FILE DOES
    retrieve() embeds the question with the same model that embedded the
    documents (vector/embedding.py), asks ChromaDB for the nearest chunks, and
    drops any whose distance is above `max_distance` (0.7): a weak match would
    only dilute the prompt and invite a made-up answer.

WHERE IT SITS
    features/chat/service.py run_chat() (step 1)
        --> THIS FILE --> vector/embedding.py get_model / get_collection --> ChromaDB
"""

from vector.embedding import get_collection, get_model


def retrieve(query: str, n_results: int = 5, where: dict = None, max_distance: float = 0.7):
    """
    The closest chunks, nearest first: [{"id", "document", "metadata", "distance"}].
    An empty list means nothing was close enough (the chat then answers 404).

    Parameters (where they come from — features/chat/service.py run_chat):
        query        - the user's question.
        n_results    - ChatRequest.n_results (default 5): chunks asked from ChromaDB
                       BEFORE the distance filter, so fewer may come back.
        where        - {"proposal_id": ...} when the request names a proposal, else None.
        max_distance - 0.7 (cosine-style distance; lower = closer in meaning).
    """
    query_embedding = get_model().encode(query).tolist()
    results = get_collection().query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where
    )

    chunks = []
    for doc, meta, dist, chunk_id in zip(
        results["documents"][0], results["metadatas"][0],
        results["distances"][0], results["ids"][0]
    ):
        if dist <= max_distance:
            chunks.append({"id": chunk_id, "document": doc, "metadata": meta, "distance": dist})

    return chunks


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/context.py — run_chat() adds the database facts
#   (enrich_chunks, collect_facts) to these chunks.
# If the index is empty or out of date: run python -m vector.embedding.
# First call in a process loads the embedding model (a few seconds); later calls reuse it.
