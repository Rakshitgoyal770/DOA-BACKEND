# features/chat/prompt.py
"""Builds the LLM messages from retrieved chunks and (optionally) SQL proposal facts."""

from features.chat.context import format_facts, source_label

SYSTEM_PROMPT = (
    "You answer questions about DAO governance using ONLY the provided material. "
    "Cite text from the sources as [Source N]. Use PROPOSAL FACTS for results, turnout and "
    "voting-power numbers and cite them as [Facts]. Author details in a source header "
    "(wallet, voting power, how they voted) come from linking forum usernames to wallets; "
    "a 'wallet link' of low or medium confidence is a likely, unverified match, so say so "
    "when you rely on it. If the material doesn't contain enough information, say so "
    "explicitly rather than guessing."
)


def build_prompt(query: str, chunks: list[dict], facts: list[dict] | None = None) -> list[dict]:
    """chunks may carry chunk['sql'] (see context.enrich_chunks); facts come from context.collect_facts."""
    context = "\n\n".join(
        f"[{source_label(i + 1, c)}] {c['document']}" for i, c in enumerate(chunks)
    )
    facts_block = ""
    if facts:
        facts_block = "PROPOSAL FACTS (from the database):\n" + "\n".join(format_facts(f) for f in facts) + "\n\n"

    user_prompt = f"{facts_block}Sources:\n{context}\n\nQuestion: {query}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
