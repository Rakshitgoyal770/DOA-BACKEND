# vector/chunking.py
"""
vector/chunking.py — Splits text into pieces small enough to be searched, and documents WHY.

WHY CHUNK AT ALL
    The embedding model (BAAI/bge-small-en-v1.5) reads at most 512 tokens (about
    1,800 characters of normal English). Anything after that is silently ignored, so
    a long text embedded whole can only be found by its first ~400 words. Before this
    file split forum posts, 17% of them were longer than that limit and 46.8% of all
    forum text was invisible to search. A chunk must therefore be well under 512 tokens.
    Smaller chunks also keep the prompt small (the free Groq tier rejects requests over
    8,000 tokens) and make each retrieved passage about one thing.

THE CHUNKING STRATEGIES IN USE (the complete list)
    +---------------------+----------------------------------+--------------------+------------------+
    | What                | Strategy                         | Chunk size         | Where it is used |
    +---------------------+----------------------------------+--------------------+------------------+
    | Proposal body       | paragraphs packed together up to | <= 1500 characters | vector/embedding |
    |                     | the limit; a paragraph that is   | (PROPOSAL_MAX_CHARS)| proposal_documents|
    |                     | too long is split by sentence    |                    |                  |
    | Forum post          | a post that fits is ONE chunk;   | <= 1200 characters | vector/embedding |
    |                     | a longer one is split by sentence| (FORUM_MAX_CHARS)  | forum_documents  |
    | Prompt, per source  | not chunking: a safety cap that  | <= 2000 characters | features/chat/   |
    |                     | cuts any single source off       | (MAX_SOURCE_CHARS) | prompt.py        |
    +---------------------+----------------------------------+--------------------+------------------+
    Both indexed kinds use the same function, chunk_text(), with a different limit.

TWO LIMITS, BOTH ENFORCED
    * Characters (the numbers above): a fast first limit.
    * Tokens (MAX_TOKENS = 500): the real limit. Characters alone cannot guarantee the
      512-token cap, because tables, URLs and hashes turn into many tokens (we measured
      proposal chunks of 1,500 characters that were 876 tokens). vector/embedding.py
      passes in the embedding model's own tokenizer to count them. Without a counter
      (unit tests) only the character limit applies.

HOW chunk_text SPLITS (three levels, finest only when needed)
    1. Paragraphs   blank-line breaks. Proposal bodies have them.
    2. Sentences    ". ", "! ", "? ". Forum posts need this level: our HTML cleaner
                    collapses all whitespace, so a stored forum post has NO line breaks.
    3. Words        only for a "sentence" longer than the limit (a pasted table, a long
                    URL list), which is cut at a space.
    Pieces are then packed greedily into chunks up to the limit, in order, so a chunk
    never ends in the middle of a word and almost never in the middle of a sentence.

DECISIONS WORTH KNOWING
    * Why 1200 / 1500 characters: roughly 300-400 tokens for normal prose; the token limit
      above catches the text that tokenises badly. tests/test_chunking.py checks the real
      data: no chunk over 512 tokens.
    * No overlap between chunks. Overlap helps when a split can cut a thought in two; our
      splits land on sentence boundaries. It would also duplicate text in the prompt.
    * Every chunk of a post carries the post's metadata (author, wallet, voting power), so
      any chunk can be traced back to its author.
    * Short texts are never split, so most documents keep exactly the id they always had.

WHERE IT SITS
    vector/embedding.py proposal_documents() / forum_documents() --> THIS FILE
"""

import re
from typing import Callable

PROPOSAL_MAX_CHARS = 1500
FORUM_MAX_CHARS = 1200
MAX_TOKENS = 500          # the model's limit is 512, which includes 2 special tokens

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _cut(word: str, fits: Callable[[str], bool]) -> list[str]:
    """
    Cut one unbroken string (a long URL or hash) in halves until every part fits.

    Parameters (where they come from — _split_long): the string and the fits() test.
    """
    if fits(word) or len(word) <= 1:
        return [word]
    middle = len(word) // 2
    return _cut(word[:middle], fits) + _cut(word[middle:], fits)


def _split_long(piece: str, fits: Callable[[str], bool]) -> list[str]:
    """
    Split one piece that does not fit: by sentence first, and any sentence still too
    long by words. Each returned part fits.

    Parameters (where they come from — chunk_text):
        piece - a paragraph that does not fit.
        fits  - chunk_text's test: within the character and token limits.
    """
    parts = []
    for sentence in _SENTENCE_END.split(piece):
        if fits(sentence):
            parts.append(sentence)
            continue
        current = ""                                         # a very long "sentence": cut at spaces
        for word in sentence.split(" "):
            candidate = f"{current} {word}" if current else word
            if current and not fits(candidate):
                parts.append(current)
                current = word
            else:
                current = candidate
            if not fits(current):                            # one unbroken word that is too long
                parts.extend(_cut(current, fits)[:-1])
                current = _cut(current, fits)[-1]
        if current:
            parts.append(current)
    return parts


def chunk_text(text: str | None, max_chars: int, count_tokens: Callable[[str], int] | None = None,
               max_tokens: int = MAX_TOKENS) -> list[str]:
    """
    The text as a list of chunks, in order, each within the character limit and (when a
    counter is given) the token limit. A text that fits is returned as one chunk, unchanged.

    Parameters (where they come from):
        text         - proposals.body or forum_posts.content, via vector/embedding.py.
        max_chars    - PROPOSAL_MAX_CHARS for proposal bodies, FORUM_MAX_CHARS for forum posts.
        count_tokens - the embedding model's tokenizer as a function (vector/embedding.py
                       token_counter); None = character limit only.
        max_tokens   - MAX_TOKENS.
    Changing a limit changes the chunks, so the next index sync re-embeds the affected
    documents (python -m vector.embedding --dry-run shows how many).
    """
    def fits(candidate: str) -> bool:
        return len(candidate) <= max_chars and (count_tokens is None or count_tokens(candidate) <= max_tokens)

    text = (text or "").strip()
    if not text:
        return []
    if fits(text):
        return [text]

    # Each piece is (text, separator to put before it when it joins the previous piece):
    # a blank line between paragraphs, a plain space between parts of ONE split paragraph.
    pieces = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        parts = [paragraph] if fits(paragraph) else _split_long(paragraph, fits)
        pieces.append((parts[0], "\n\n"))
        pieces.extend((part, " ") for part in parts[1:])

    chunks, current = [], ""
    for piece, separator in pieces:
        joined = f"{current}{separator}{piece}" if current else piece
        if current and not fits(joined):
            chunks.append(current)
            current = piece
        else:
            current = joined
    if current:
        chunks.append(current)
    return chunks


# ── Where control goes next ───────────────────────────────────────────────────
# Back to vector/embedding.py, which names each chunk (proposal_<pid>_<n>,
# forum_post_<pid>_<post>[_c<n>]) and embeds it if it is new or its text changed.
# If a chunk is still found to be too long for the model: lower the limit here and
#   run python -m vector.embedding.
