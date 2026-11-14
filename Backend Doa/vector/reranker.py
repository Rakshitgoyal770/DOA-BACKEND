# vector/reranker.py
"""
vector/reranker.py — Re-orders the candidate passages by reading each one TOGETHER with the question.

WHY
    The vector search compares a question and a passage that were each turned into numbers
    separately; the keyword search only counts shared words. A reranker (a "cross-encoder")
    reads the question and one passage as a single text and scores how well the passage
    answers the question. It is too slow to run over every chunk, so it only re-orders the
    ~30 candidates the two searches found.

    Measured on eval/retrieval_set.json, on top of the merged vector + keyword result:
        the right passage ranked FIRST: 51% -> 77%;  in the top 5: 91% -> 93%
        cost: about 1 second per search on a laptop CPU (30 passages)
    A larger model (BAAI/bge-reranker-base) was also tried: 8.6 seconds per search and worse
    results on our data, so it is not used.

WHAT THIS FILE DOES
    get_reranker()   loads the model once (about 90 MB, downloaded on first use).
    rerank()         candidates -> the same candidates, best first, each with "rerank_score".
                     If the model cannot be loaded (no network on the very first use), the
                     candidates come back in the order they arrived: search still works.

WHERE IT SITS
    features/chat/retrieval.py retrieve() --> THIS FILE
"""

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
MAX_TOKENS = 512          # question + passage; a longer pair is cut at the end by the model
BATCH_SIZE = 16


@lru_cache(maxsize=1)
def get_reranker():
    """The cross-encoder, or None if it cannot be loaded (logged once)."""
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(MODEL_NAME, max_length=MAX_TOKENS)
    except Exception as error:                      # no network for the first download, a broken install, ...
        logger.warning("Reranker %s is not available, passages keep their merged order: %s", MODEL_NAME, error)
        return None


def rerank(question: str, candidates: list[dict], text_of=None, model=None) -> list[dict]:
    """
    The candidates ordered by how well each answers the question, best first. Each gets
    "rerank_score" (higher = better; only comparable within one question).

    Parameters (where they come from — features/chat/retrieval.py retrieve):
        question   - the search sentence.
        candidates - chunks ({"document", "metadata", ...}), in their merged order.
        text_of    - chunk -> the text the model reads for it. Default: its document.
        model      - anything with predict([(question, text), ...]) -> scores. None = get_reranker().
    """
    if not candidates:
        return []
    model = model if model is not None else get_reranker()
    if model is None:
        return candidates
    text_of = text_of or (lambda chunk: chunk["document"])
    scores = model.predict([(question, text_of(c)) for c in candidates], batch_size=BATCH_SIZE,
                           show_progress_bar=False)
    for chunk, score in zip(candidates, scores):
        chunk["rerank_score"] = float(score)
    # sorted() is stable: equal scores keep their merged order
    return sorted(candidates, key=lambda c: -c["rerank_score"])
