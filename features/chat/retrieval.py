# features/chat/retrieval.py
"""Vector search: embed the query, query ChromaDB, drop chunks that are too far away."""

from vector.embedding import collection, model


def retrieve(query: str, n_results: int = 5, where: dict = None, max_distance: float = 0.7):
    query_embedding = model.encode(query).tolist()
    results = collection.query(
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
