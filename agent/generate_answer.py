
from agent.llm_provider import generate
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


def build_prompt(query: str, chunks: list[dict]) -> list[dict]:
    context = "\n\n".join(
        f"[Source {i+1} - {c['metadata'].get('source_type')}] {c['document']}"
        for i, c in enumerate(chunks)
    )

    system_prompt = (
        "You answer questions about DAO governance using ONLY the provided sources. "
        "Cite sources as [Source N]. If the sources don't contain enough information, "
        "say so explicitly rather than guessing."
    )

    user_prompt = f"Sources:\n{context}\n\nQuestion: {query}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def answer_question(query: str, chunks: list[dict]) -> tuple[str, str]:
    messages = build_prompt(query, chunks)
    answer, provider = generate(messages)
    return answer, provider