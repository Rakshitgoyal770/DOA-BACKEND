# features/chat/llm.py
"""
features/chat/llm.py — Sends the prompt to an LLM, falling back across free providers.

WHAT THIS FILE DOES
    generate() tries each provider in PROVIDERS order and returns the first answer:
        groq -> gemini -> openrouter (tries 4 free models)
    Free tiers rate-limit often (HTTP 429) or are briefly overloaded (503); the
    fallback keeps the chat answering. The provider that answered is returned
    too, so the API response and the evaluation can show who answered.

    generate_with_tools() is the same idea for the AGENT (features/chat/agent.py): the
    model may reply with a request to run a lookup (reply.tool_calls) instead of text.
    Only groq, gemini, groq-small and openrouter are tried: all accept the OpenAI "tools" format
    (Gemini through its OpenAI-compatible endpoint), so one conversation can continue on any of them.

    Both functions wait and retry once when a provider says "try again in 4.8s" (Groq's
    tokens-per-minute limit), as long as the wait is short: a few seconds is cheaper than
    falling back to a weaker provider or using up Gemini's 20 requests a day.

CHECK YOUR PROVIDERS
    python -m features.chat.llm --openrouter   lists which OpenRouter free models are still free
    (free models disappear without notice; no key or quota needed)
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
import re
import time

from dotenv import load_dotenv

load_dotenv()

RETRY_MAX_SECONDS = 15      # wait at most this long for a rate limit to clear
LLM_TIMEOUT_SECONDS = 45    # a request that takes longer fails, and the next provider is tried (the
                            # openai package would otherwise wait 10 minutes, and retry twice)


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




# Free models change often: three of the four we listed earlier stopped being free (HTTP 404
# "unavailable for free"), and the fallback skipped them silently. These four were tested on
# 2026-10-27 with our real tools and picked the right lookup 3 times out of 3. Re-check with
#   python -m features.chat.llm --openrouter
# which lists which of them still work.
OPENROUTER_FREE_MODELS = [
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "poolside/laguna-s-2.1:free",
    "nvidia/nemotron-3.5-lightning:free",
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
            return _with_retry(call_fn, messages), name
        except Exception as e:
            print(f"  [{name} failed: {e}] falling back...")
            last_error = e
            continue
    raise RuntimeError(f"All providers failed. Last error: {last_error}")


def _retry_delay(error: Exception) -> float | None:
    """Seconds a rate-limit error asks us to wait ('Please try again in 4.83s' / '1m3.2s'), or None."""
    m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)s", str(error))
    return int(m.group(1) or 0) * 60 + float(m.group(2)) if m else None


def _with_retry(call, *args):
    """
    call(*args), and once more after the wait when the error says how long to wait
    and that wait is at most RETRY_MAX_SECONDS. Any other error is raised unchanged.

    Parameters (where they come from): a provider function and its arguments, from generate()
    or generate_with_tools().
    """
    try:
        return call(*args)
    except Exception as e:
        delay = _retry_delay(e)
        if delay is None or delay > RETRY_MAX_SECONDS:
            raise
        time.sleep(delay + 0.5)
        return call(*args)


# ── Tool calling (used by the agent) ──────────────────────────────────────────

def _tool_client_groq():
    from groq import Groq
    return (Groq(api_key=os.environ["GROQ_API_KEY"], timeout=LLM_TIMEOUT_SECONDS, max_retries=1),
            os.environ.get("GROQ_TOOL_MODEL", "openai/gpt-oss-120b"))


def _tool_client_gemini():
    from openai import OpenAI
    return (OpenAI(api_key=os.environ["GEMINI_API_KEY"], timeout=LLM_TIMEOUT_SECONDS, max_retries=0,
                   base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
            "gemini-3.6-flash")


def _tool_client_openrouter():
    """OpenRouter's first free model that accepts tools. Last resort for the agent: its free tier is
    small (about 50 requests a day) and the writer depends on it, so the others are tried first."""
    from openai import OpenAI
    return (OpenAI(api_key=os.environ["OPENROUTER_API_KEY"], base_url="https://openrouter.ai/api/v1",
                   timeout=LLM_TIMEOUT_SECONDS, max_retries=0),
            OPENROUTER_FREE_MODELS[0])


def _tool_client_groq_small():
    """Groq's smaller model: weaker, but Groq counts each model's daily tokens separately, so it
    still answers after the big model's 200,000 tokens a day are used up."""
    from groq import Groq
    return Groq(api_key=os.environ["GROQ_API_KEY"], timeout=LLM_TIMEOUT_SECONDS, max_retries=1), "openai/gpt-oss-20b"


# Best first. Without the last one the whole question failed when Groq's big model and Gemini's
# 20 requests a day were both used up (the writer still answered through OpenRouter).
TOOL_PROVIDERS = [("groq", _tool_client_groq), ("gemini", _tool_client_gemini),
                  ("groq-small", _tool_client_groq_small), ("openrouter", _tool_client_openrouter)]

# Gemini refuses tool-call messages written by another model ("Function call is missing a
# thought_signature"), which is exactly what a fallback in the middle of a conversation sends.
# So it never gets tool-call messages: the lookups so far are given to it as plain text.
FLATTEN_HISTORY = {"gemini"}


def flatten_tool_history(messages: list[dict]) -> list[dict]:
    """
    The same conversation without tool-call messages: the lookups already run and their results
    become one user message after the other messages.

    Parameter (where it comes from): the messages gather_evidence built, via generate_with_tools.
    """
    out, asked, results = [], {}, []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            asked.update({tc["id"]: tc["function"] for tc in m["tool_calls"]})
        elif m["role"] == "tool":
            f = asked.get(m["tool_call_id"], {})
            results.append(f"- {f.get('name')}({f.get('arguments')}):\n  {m['content']}")
        else:
            out.append(m)
    if results:
        out.append({"role": "user", "content": "Lookups already run, with their results:\n" + "\n".join(results)
                    + "\nRun any further lookup that is still needed, or reply DONE."})
    return out


def generate_with_tools(messages: list[dict], tools: list[dict]):
    """
    (reply message, provider name) from the first provider that answers. The reply has
    .content (text) and .tool_calls (lookups the model wants run; None when it answered).

    Parameters (where they come from — features/chat/agent.py gather_evidence):
        messages - the whole conversation so far, in OpenAI format (system, user, and
                   the assistant / tool messages added after each lookup).
        tools    - features/chat/tools.py TOOLS.
    Raises RuntimeError if every provider fails.
    """
    def call(make_client, history):
        client, model = make_client()
        resp = client.chat.completions.create(model=model, messages=history, tools=tools, tool_choice="auto")
        return resp.choices[0].message

    last_error = None
    for name, make_client in TOOL_PROVIDERS:
        try:
            return _with_retry(call, make_client,
                               flatten_tool_history(messages) if name in FLATTEN_HISTORY else messages), name
        except Exception as e:
            print(f"  [{name} failed: {' '.join(str(e).split())[:200]}] falling back...")
            last_error = e
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


def openrouter_free_models() -> dict[str, bool]:
    """
    {model id: supports tools} for every model OpenRouter currently offers for free.
    Reads OpenRouter's public model list: no API key, no quota used.
    """
    import requests
    models = requests.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]
    return {m["id"]: "tools" in (m.get("supported_parameters") or []) for m in models
            if str(m.get("pricing", {}).get("prompt")) in ("0", "0.0")
            and str(m.get("pricing", {}).get("completion")) in ("0", "0.0")}


def check_openrouter_models() -> list[str]:
    """
    Print whether each model in OPENROUTER_FREE_MODELS is still free, and which other free
    models accept tools. Returns the ids of OUR models that are no longer free.
    """
    free = openrouter_free_models()
    gone = [m for m in OPENROUTER_FREE_MODELS if m not in free]
    for m in OPENROUTER_FREE_MODELS:
        print(f"  {'GONE (not free any more)' if m in gone else 'free' + (', tools ok' if free[m] else ', NO tools'):<26} {m}")
    others = sorted(m for m, tools in free.items() if tools and m not in OPENROUTER_FREE_MODELS)
    print(f"  other free models with tools ({len(others)}): " + ", ".join(others))
    return gone


if __name__ == "__main__":
    # python -m features.chat.llm [--openrouter]
    import sys
    if "--openrouter" in sys.argv:
        check_openrouter_models()
    else:
        check_providers()


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/service.py, which hands the answer back to
#   features/chat/routes.py (POST /chat) or eval/eval_harness.py.
# If every provider fails: RuntimeError -> the API returns HTTP 500.
# A failing provider is only printed ("[groq failed: ...] falling back...");
#   run python -m features.chat.llm to see each provider's status and error at once.
