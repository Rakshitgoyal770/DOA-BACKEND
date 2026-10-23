# features/chat/llm.py
"""
features/chat/llm.py — Sends the prompt to an LLM, falling back across free providers.

WHAT THIS FILE DOES
    generate() tries each provider in PROVIDERS order and returns the first answer:
        groq -> gemini -> openrouter (tries 4 free models)
    Free tiers rate-limit often (HTTP 429) or are briefly overloaded (503); the
    fallback keeps the chat answering. The provider that answered is returned
    too, so the API response and the evaluation can show who answered.

CHECK YOUR PROVIDERS
    python -m features.chat.llm      tests EACH provider separately and shows why one fails
    (missing package, missing key, exhausted free quota ...). Run it with the same Python
    you use for the server / evaluation: a package installed in .venv is not installed in
    the global Python, and the other way round.

SETUP
    API keys come from the .env file (loaded below): GROQ_API_KEY, GEMINI_API_KEY,
    OPENROUTER_API_KEY. A provider whose key or Python package is missing
    simply fails and the next one is tried. (Mistral was removed on purpose.)

WHERE IT SITS
    features/chat/service.py answer_question()  --+
    eval/eval_harness.py (the LLM judge)        --+--> THIS FILE --> provider APIs
"""

import os

from dotenv import load_dotenv

load_dotenv()


def call_groq(messages):
    """Groq (fast). Parameter: messages from features/chat/prompt.py build_prompt."""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=messages,
    )
    return resp.choices[0].message.content


def call_gemini(messages):
    """Google Gemini. Its API takes one text, so the messages are joined (the system
    rules become the first paragraph). Parameter: messages from build_prompt."""
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = "\n".join(m["content"] for m in messages)
    resp = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    return resp.text




OPENROUTER_FREE_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3.8-27b:free",
]


def call_openrouter(messages):
    """OpenRouter: tries each free model in OPENROUTER_FREE_MODELS until one answers.
    Parameter: messages from build_prompt."""
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
]


def generate(messages: list[dict]) -> tuple[str, str]:
    """
    (answer text, provider name) from the first provider that answers.

    Parameter (where it comes from):
        messages - [{"role": "system", ...}, {"role": "user", ...}] from
                   features/chat/prompt.py build_prompt (via service.answer_question),
                   or a single judge prompt from eval/eval_harness.py.
    Raises RuntimeError if every provider fails.
    """
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


def check_providers() -> dict[str, str]:
    """
    Send one tiny request to EVERY provider, one by one (not the fallback chain),
    and print which work and why the others fail. Returns {provider: "ok" | error}.
    Each working provider uses one request of its free quota.
    """
    import time
    ping = [{"role": "user", "content": "Reply with the single word: ok"}]
    status = {}
    for name, call in PROVIDERS:
        started = time.time()
        try:
            call(ping)
            status[name] = "ok"
            print(f"  {name:<11} WORKS  ({time.time() - started:.1f}s)")
        except Exception as e:
            status[name] = " ".join(f"{type(e).__name__}: {e}".split())     # one line, no line breaks
            print(f"  {name:<11} FAILS  {status[name][:300]}")
    return status


if __name__ == "__main__":
    # python -m features.chat.llm
    check_providers()


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/service.py, which hands the answer back to
#   features/chat/routes.py (POST /chat) or eval/eval_harness.py.
# If every provider fails: RuntimeError -> the API returns HTTP 500.
# A failing provider is only printed ("[groq failed: ...] falling back...");
#   run python -m features.chat.llm to see each provider's status and error at once.
