# test_openrouter_nemotron.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

key = os.environ.get("OPENROUTER_API_KEY")
print("Key loaded:", key[:10] + "..." if key else "NONE")

client = OpenAI(
    api_key=key,
    base_url="https://openrouter.ai/api/v1",
)

resp = client.chat.completions.create(
    model="nvidia/nemotron-3-ultra-550b-a55b:free",
    messages=[{"role": "user", "content": "arbitrum??"}]
)

print(resp.choices[0].message.content)