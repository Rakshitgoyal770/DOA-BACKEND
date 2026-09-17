# vector/test_chroma.py
import chromadb
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = chromadb.PersistentClient(path="./chroma_data")

collection = client.get_or_create_collection(name="dao_chunks")

# Real content from your Good Entry data
text = "Voting FOR. Sad to read proposals like this one. I'll be voting to ban all three, the worst one being Limitless."
embedding = model.encode(text).tolist()  # Chroma wants a plain list, not a numpy array

collection.add(
    ids=["zeptimus_post_1"],
    embeddings=[embedding],
    documents=[text],
    metadatas=[{
        "proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
        "source_type": "forum_post",
        "author": "Zeptimus",
    }]
)

# Test 1: similarity search
query = "did anyone explain why they voted this way"
query_embedding = model.encode(query).tolist()

results = collection.query(query_embeddings=[query_embedding], n_results=1)
print("Similarity search result:")
print(results["documents"])

# Test 2: metadata-filtered search (this is the scoping mechanism your whole architecture needs)
filtered_results = collection.query(
    query_embeddings=[query_embedding],
    n_results=1,
    where={"proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c"}
)
print("\nFiltered search result:")
print(filtered_results["documents"])