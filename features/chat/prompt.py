# features/chat/prompt.py
"""
features/chat/prompt.py — Writes the exact text the LLM receives.

WHAT THIS FILE DOES
    STAGE 2 (the writer). build_prompt() turns the evidence the agent gathered
    (features/chat/agent.py) into two chat messages:
        system: the rules — specific facts ONLY from the material (cited as
                [Source N] / [Facts]); general background allowed but marked
                [Background]; flag low-confidence wallet links; say so when
                information is missing
        user:   DATABASE FACTS (one entry per lookup: what was asked, what the database
                returned)  +  numbered sources (forum passages, each with its author's
                wallet and vote)  +  the question
    Example of the user message:
        DATABASE FACTS (lookups run in the database for this question):
        - list_proposals(order_by=voters, limit=1):
          {"scope": "all 118 proposals we hold for all 5 DAOs ...", "proposals": [{"title": ...}]}
        Sources:
        [Source 1 - forum_post by OPUser (wallet link: low)] Glad to see you here...
        Question: Why did people support it?

ADVICE MODE
    When the user asks how they should vote ("Should I vote for this?"),
    is_advice_question() is true and ADVICE_RULES are added to the system message.
    The assistant must then give a balanced briefing (what it asks, arguments for,
    arguments against, where the vote stands, who is on which side) and must NOT
    tell the user how to vote. Every other question gets the normal prompt, unchanged.

WHERE IT SITS
    features/chat/service.py run_chat() / answer_question()
        --> THIS FILE (uses context.source_label and tools.result_json)
        --> features/chat/llm.py generate()
"""

import re

from features.chat.context import source_label
from features.chat.tools import result_json

# Specific facts come only from our data; general background may come from the
# model's own knowledge, but must be marked so the reader (and the evaluation)
# can tell the two apart. eval/eval_harness.py relies on the "[Background]" marker.
BACKGROUND_TAG = "[Background]"

# Safety cap on ONE source's text in the prompt. Indexed chunks are already at most
# 1,500 characters (vector/chunking.py); this only protects against an oversized source
# (an old, unchunked index entry) pushing a request past the free LLM tiers' limit
# (Groq rejects requests over 8,000 tokens per minute).
MAX_SOURCE_CHARS = 2000
SHORTENED_MARK = " [...source shortened]"
MAX_SOURCES = 8            # passages in the prompt: the closest ones, however many searches ran

SYSTEM_PROMPT = (
    "You answer questions about DAO governance.\n"
    "1. For anything about specific proposals, votes, results, numbers, voting power, people "
    "or recent events, use ONLY the provided material. Cite source text as [Source N] and "
    "DATABASE FACTS as [Facts]. DATABASE FACTS are exactly what our lookups returned: a "
    "'scope' field says which proposals a ranking covers, and our data holds only the most "
    "recent proposals of each DAO, so say 'among the proposals in our data' when you rank or "
    "count them. Never add a token name or unit to voting power. A ballot like 'A: 6600000, "
    "B: 13200000' shows how the voter split their voting power. While a vote is still 'active' "
    "its top choice is 'leading', never the winner. 'Silence ratio' means forum posters "
    "divided by voters. Never count people or posts yourself from the sources (they are only a "
    "few passages): counts come from the DATABASE FACTS, or you say they are not available.\n"
    f"2. You may add general background from your own knowledge (what a DAO, a governance "
    f"mechanism or a well-known protocol is), but start each such sentence with {BACKGROUND_TAG}. "
    "Add background only when it helps answer the question; never pad an answer with it. "
    "Never use your own knowledge for numbers, vote results, who voted or what happened recently.\n"
    "3. Author details in a source header (wallet, voting power, how they voted) come from "
    "linking forum usernames to wallets; a 'wallet link' of low or medium confidence is a "
    "likely, unverified match, so say so when you rely on it.\n"
    "4. If the material does not contain the specific information asked for, say so plainly "
    "instead of guessing, in everyday words (never say 'the material', 'the sources' or 'the "
    "provided data' when nothing was found), and say what you can help with: rankings of "
    "proposals, a proposal's result and turnout, who voted how, and what people argued on the "
    "forums, for Arbitrum, Aave, Optimism, Uniswap and ENS. Reply with a greeting ONLY when the "
    "whole message is nothing but a greeting or thanks: then answer in ONE short sentence that "
    "greets back and asks how you can help with DAO governance, without listing what you can do. "
    "If there is any question or request in the message (for example 'hi, what is new?'), do not "
    "greet: begin directly with the answer.\n"
    "5. Write like a knowledgeable colleague who wants the reader to understand, not like a database dump.\n"
    "- Start with the direct answer in one plain sentence that says what the reader asked for, with the "
    "number or the name in it (not a sentence that only describes the list that follows).\n"
    "- When there are several items, give a short list: one line each, the name in bold, then its key "
    "facts as a natural phrase such as '1,019 voters, leading For 93.8%' (never 'field: value' pairs "
    "like 'voters: 1,019'). Order them so the reader sees the point (newest first, open ones first).\n"
    "- Name every proposal by its title. Never show a proposal id (the long 0x... code) to the reader.\n"
    "- Never end with 'Let me know...' or any other closing line, except the one offer described below.\n"
    "- You may end with ONE short takeaway sentence, only when the numbers you showed support it (for "
    "example 'all five lean strongly For'). Never use words like 'hot', 'surging' or 'booming' and never "
    "claim a trend unless the facts contain numbers over time that show it.\n"
    "- Our data can be days old: say 'as of our latest data' and never 'currently', 'right now' or "
    "'still' about a vote that is not closed.\n"
    "- Explain a term in a few words the first time you use it (voting power, silence ratio, 'leading').\n"
    "- Copy every number exactly as it appears in the facts. You may add commas to a whole number "
    "(63845 -> 63,845) but never change a decimal (11.549 stays 11.549), never shorten a number "
    "(63.8K) and never write a number in words.\n"
    "- Put a citation once at the end of the sentence or list line it supports, not after every number.\n"
    "- Keep it short, no tables unless asked. When you name a voter, also give their voting power and "
    "how they voted if you have it.\n"
    "- Only after a list of several proposals, you may add one short offer to go deeper (for example "
    "'Want the reasons people gave on any of these?'). Never after any other kind of answer."
)

# Added to the system message only for "how should I vote?" questions.
ADVICE_RULES = (
    "\n\nADVICE MODE - the user is asking how to vote.\n"
    "You must NOT tell the user how to vote, which option to choose, or whether they should "
    "support or oppose the proposal. Never write things like 'vote For if...' or 'I would "
    "vote...'. Give a balanced briefing instead, in this order:\n"
    "(a) What the proposal asks for, in one or two sentences.\n"
    "(b) The strongest arguments in favour, with citations.\n"
    "(c) The strongest concerns or arguments against, with citations.\n"
    "Use ONLY arguments that appear in the sources. Never add an argument the sources do not "
    "contain, not even a 'typical' or 'common' one. If a side has no argument in the sources, "
    "write 'The sources contain no arguments for/against this proposal.' for that side.\n"
    "(d) Where the vote stands, from the DATABASE FACTS (result or current standing, turnout), and "
    "which linked delegates took which side with their voting power, noting when a wallet link "
    "is only low or medium confidence.\n"
    "(e) Finish with this sentence: 'This is a summary of the arguments, not a voting "
    "recommendation - the decision is yours.'\n"
    "If it is not clear which proposal the question is about, ask which one instead of "
    "answering. If the user states their own priorities, you may say which arguments relate to "
    "them, but still do not choose for them."
)

# Phrasings of "how should I vote?". Deliberately narrow: questions ABOUT votes
# ("How did X vote?", "Who voted against it?", "Why did it pass?") must not match.
_ADVICE_PATTERNS = [
    r"\bshould\s+(i|we)\b[^?]{0,60}\bvot",                       # should I vote / should we vote
    r"\b(how|what|where|which\s+way)\s+(should|would)\s+(i|we|you)\b[^?]{0,60}\bvot",
    r"\bhow\s+do\s+you\s+think\s+(i|we)\s+should\b[^?]{0,60}\bvot",
    r"\bwhat\s+would\s+you\s+vote\b",
    r"\b(recommend|advise|advice|suggest)\b[^?]{0,60}\bvot",     # recommend how to vote
    r"\bvot\w*\b[^?]{0,40}\b(recommend|advice)\b",
    r"\bworth\s+(voting|supporting)\b",
    r"\bgood\s+idea\s+to\s+(vote|support)\b",
]
_ADVICE_RE = re.compile("|".join(_ADVICE_PATTERNS), re.IGNORECASE)


def clip_source(text: str) -> str:
    """
    A source's text, cut at a word boundary if it is longer than MAX_SOURCE_CHARS.

    Parameter (where it comes from):
        text - a retrieved chunk's document, from build_prompt.
    """
    if len(text) <= MAX_SOURCE_CHARS:
        return text
    return text[:MAX_SOURCE_CHARS].rsplit(" ", 1)[0] + SHORTENED_MARK


def is_advice_question(query: str) -> bool:
    """
    True if the user is asking how they should vote (so ADVICE_RULES apply).

    Parameter (where it comes from):
        query - the user's question, passed through build_prompt from run_chat
                (ChatRequest.query, or a golden-dataset question in the evaluation).
    """
    return bool(_ADVICE_RE.search(query or ""))


def split_evidence(evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    (passages, fact entries) from the agent's evidence.

    Passages are the chunks of every forum search that found something: de-duplicated by id,
    closest first, at most MAX_SOURCES. Fact entries are every other lookup, plus searches
    that found nothing (so the writer can say that nothing was found).

    Parameter (where it comes from): the list gather_evidence() returned, via run_chat().
    """
    chunks, entries = {}, []
    for e in evidence:
        found = e["result"].get("chunks") if e["tool"] == "search_forum" and isinstance(e["result"], dict) else None
        if found:
            for c in found:
                chunks.setdefault(c["id"], c)
        else:
            entries.append(e)
    return sorted(chunks.values(), key=lambda c: c["distance"])[:MAX_SOURCES], entries


def format_facts(entries: list[dict]) -> str:
    """
    The DATABASE FACTS block: one entry per lookup, 'name(arguments):' then its result as JSON.
    "" when there are no entries.

    Parameter (where it comes from): the second value of split_evidence().
    """
    if not entries:
        return ""
    lines = ["DATABASE FACTS (lookups run in the database for this question):"]
    for e in entries:
        arguments = ", ".join(f"{k}={v}" for k, v in e["arguments"].items())
        lines.append(f"- {e['tool']}({arguments}):\n  {result_json(e['result'])}")
    return "\n".join(lines)


def build_prompt(query: str, evidence: list[dict]) -> list[dict]:
    """
    The two messages ([system, user]) sent to the LLM.

    Parameters (where they come from — features/chat/service.py answer_question):
        query    - the user's question (ChatRequest.query or a golden-dataset question).
        evidence - what features/chat/agent.py gather_evidence() collected; [] when the
                   question needed no lookup (the writer then answers from general
                   background only, marked [Background], or says it has no data).
    Advice questions get ADVICE_RULES appended to the system message. Each source is cut
    to MAX_SOURCE_CHARS (clip_source); nothing else changes.
    """
    chunks, entries = split_evidence(evidence)
    context = "\n\n".join(
        f"[{source_label(i + 1, c)}] {clip_source(c['document'])}" for i, c in enumerate(chunks)
    )
    facts_block = format_facts(entries)
    user_prompt = (f"{facts_block}\n\n" if facts_block else "") + \
        f"Sources:\n{context or '(no passage was found)'}\n\nQuestion: {query}"
    system = SYSTEM_PROMPT + (ADVICE_RULES if is_advice_question(query) else "")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


# ── Where control goes next ───────────────────────────────────────────────────
# Usual next file: features/chat/llm.py — generate() sends these messages to the
#   first LLM provider that answers.
# To change how the assistant behaves (tone, citation rules, advice questions),
#   edit SYSTEM_PROMPT / ADVICE_RULES here, then re-run the evaluation:
#   python -m eval.eval_harness --only advice   (then the full run, to check nothing else moved)
# If a "how should I vote" question is NOT recognised: add its phrasing to
#   _ADVICE_PATTERNS and a case to tests/test_prompt.py.
# If the writer lacks data it needs: that is a gathering problem, not a prompt problem —
#   see features/chat/agent.py (FETCHER_PROMPT) and features/chat/tools.py (TOOLS).
