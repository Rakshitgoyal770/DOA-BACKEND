# vector/test_retrieval.py
from sentence_transformers import SentenceTransformer
import chromadb

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.get_or_create_collection(name="dao_chunks")


def search(query: str, n_results: int = 5, where: dict = None):
    query_embedding = model.encode(query).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where
    )
    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        print(f"[{dist:.3f}] ({meta.get('source_type')}) {doc[:150]}...")
        print()


if __name__ == "__main__":
    print("=== Query: why was Good Entry banned ===")
    search("why was Good Entry banned", n_results=5)

    print("\n=== Scoped to Good Entry proposal only ===")
    search(
        "did anyone explain their vote",
        n_results=3,
        where={"proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c"}
    )