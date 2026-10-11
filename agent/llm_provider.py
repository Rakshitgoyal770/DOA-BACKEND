import os
from dotenv import load_dotenv

load_dotenv()


def call_groq(messages):
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
    )
    return resp.choices[0].message.content


def call_gemini(messages):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = "\n".join(m["content"] for m in messages)
    resp = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    return resp.text


def call_mistral(messages):
    from mistralai.client import Mistral
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    resp = client.chat.complete(
        model="mistral-small-latest",
        messages=messages,
    )
    return resp.choices[0].message.content


OPENROUTER_FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3.8-27b:free",
]


def call_openrouter(messages):
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    last_error = None
    for model_name in OPENROUTER_FREE_MODELS:
        try:
            resp = client.chat.completions.create(model=model_name, messages=messages)
            return resp.choices[0].message.content
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"All OpenRouter free models failed: {last_error}")


PROVIDERS = [
    ("groq", call_groq),
    ("gemini", call_gemini),
    ("openrouter", call_openrouter),
    ("mistral", call_mistral),
]


def generate(messages: list[dict]) -> tuple[str, str]:
    last_error = None
    for name, call_fn in PROVIDERS:
        try:
            result = call_fn(messages)
            return result, name
        except Exception as e:
            print(f"  [{name} failed: {e}] falling back...")
            last_error = e
            continue
    raise RuntimeError(f"All providers failed. Last error: {last_error}")


if __name__ == "__main__":
    text, provider = generate([
        {"role": "user", "content": "Say hello in one short sentence."}
    ])
    print(f"Response from {provider}: {text}")