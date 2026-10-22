# vector/chunking.py
"""
vector/chunking.py — Splits a long proposal body into search-sized pieces.

WHAT THIS FILE DOES
    A proposal body can be thousands of characters. One embedding for the whole
    text would blur its separate points together, so the body is cut into chunks
    of at most ~1,500 characters, always at paragraph breaks (blank lines), so a
    chunk never stops mid-paragraph. Forum posts are short and are NOT chunked.

WHERE IT SITS
    vector/embedding.py proposal_documents() --> THIS FILE
"""


def chunk_proposal_body(body: str, max_chars: int = 1500) -> list[str]:
    """
    The body as a list of chunks, in order. Paragraphs are packed together until
    adding the next one would reach `max_chars`; a single paragraph longer than
    that becomes its own (long) chunk rather than being cut.

    Parameters (where they come from):
        body      - proposals.body (stored by features/proposals/fetch.py),
                    passed by vector/embedding.py proposal_documents().
        max_chars - default 1500. Changing it changes every chunk, so the next
                    index sync would re-embed all proposal bodies.
    """
    if not body:
        return []
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    chunks = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) < max_chars:
            current += ("\n\n" + p if current else p)
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


# ── Where control goes next ───────────────────────────────────────────────────
# Back to vector/embedding.py, which names each chunk proposal_<proposal_id>_<n>
# and embeds it if it is new or its text changed.
