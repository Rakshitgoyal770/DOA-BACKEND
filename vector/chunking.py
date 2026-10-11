def chunk_proposal_body(body: str, max_chars: int = 1500) -> list[str]:
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
