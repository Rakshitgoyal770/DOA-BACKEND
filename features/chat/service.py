# features/chat/service.py
"""Chat pipeline: prompt -> LLM (with provider fallback)."""

from features.chat.llm import generate
from features.chat.prompt import build_prompt


def answer_question(query: str, chunks: list[dict], facts: list[dict] | None = None) -> tuple[str, str]:
    messages = build_prompt(query, chunks, facts)
    answer, provider = generate(messages)
    return answer, provider
