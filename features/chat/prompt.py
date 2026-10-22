# features/chat/prompt.py
"""
features/chat/prompt.py — Writes the exact text the LLM receives.

WHAT THIS FILE DOES
    build_prompt() turns the retrieved chunks and the database facts into two
    chat messages:
        system: the rules — specific facts ONLY from the material (cited as
                [Source N] / [Facts]); general background allowed but marked
                [Background]; flag low-confidence wallet links; say so when
                information is missing
        user:   PROPOSAL FACTS block  +  numbered sources  +  the question
    Example of the user message:
        PROPOSAL FACTS (from the database):
        - Optimism Collective | "Season 2: Cycle 8: DefiLlama" | state: closed
          result: For 91.7%; Against 1.4%; Abstain 6.9% (winner: For)
        Sources:
        [Source 1 - forum_post by OPUser (wallet link: low)] Glad to see you here...
        Question: Why did people support it?

WHERE IT SITS
    features/chat/service.py run_chat() / answer_question()
        --> THIS FILE (uses context.format_facts and context.source_label)
        --> features/chat/llm.py generate()
"""

from features.chat.context import format_facts, source_label

# Specific facts come only from our data; general background may come from the
# model's own knowledge, but must be marked so the reader (and the evaluation)
# can tell the two apart. eval/eval_harness.py relies on the "[Background]" marker.
BACKGROUND_TAG = "[Background]"

SYSTEM_PROMPT = (
    "You answer questions about DAO governance.\n"
    "1. For anything about specific proposals, votes, results, numbers, voting power, people "
    "or recent events, use ONLY the provided material. Cite source text as [Source N] and "
    "PROPOSAL FACTS as [Facts].\n"
    f"2. You may add general background from your own knowledge (what a DAO, a governance "
    f"mechanism or a well-known protocol is), but start each such sentence with {BACKGROUND_TAG}. "
    "Never use your own knowledge for numbers, vote results, who voted or what happened recently.\n"
    "3. Author details in a source header (wallet, voting power, how they voted) come from "
    "linking forum usernames to wallets; a 'wallet link' of low or medium confidence is a "
    "likely, unverified match, so say so when you rely on it.\n"
    "4. If the material does not contain the specific information asked for, say so plainly "
    "instead of guessing."
)


def build_prompt(query: str, chunks: list[dict], facts: list[dict] | None = None) -> list[dict]:
    """
    The two messages ([system, user]) sent to the LLM.

    Parameters (where they come from — features/chat/service.py answer_question):
        query  - the user's question (ChatRequest.query or a golden-dataset question).
        chunks - retrieved chunks, already enriched by context.enrich_chunks
                 (so source_label can show the author's wallet and vote).
        facts  - context.collect_facts() output; None or [] leaves the block out.
    """
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


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/llm.py — generate() sends these messages to the
#   first LLM provider that answers.
# To change how the assistant behaves (tone, citation rules, advice questions),
#   edit SYSTEM_PROMPT here, then re-run the evaluation: python -m eval.eval_harness
