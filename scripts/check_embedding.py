from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")

text = "Voting FOR. Sad to read proposals like this one. I'll be voting to ban all three, the worst one being Limitless."
vector = model.encode(text)

print("Vector length:", len(vector))
print("First 5 values:", vector[:5])