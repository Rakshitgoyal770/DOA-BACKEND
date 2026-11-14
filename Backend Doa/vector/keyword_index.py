# vector/keyword_index.py
"""
vector/keyword_index.py — Keyword search (BM25) over the same chunks the vector index holds.

WHY
    The vector search matches by meaning and is weak on exact words: a username, a ticker, a
    proposal number, "syrupUSDC". Keyword search is the opposite. On eval/retrieval_set.json
    the two together found the right passage in the top 5 for about 91% of the questions,
    against 77% for the vector search alone.

WHAT THIS FILE DOES
    KeywordIndex    scores every chunk for a question with BM25 (the standard keyword formula:
                    a word counts more when it is rare in the collection and when the chunk is
                    short) and applies the same filters as the vector search.
    get_keyword_index()
                    the index over the real Chroma collection, built in memory on first use
                    (about a second for ~6,000 chunks) and rebuilt when the number of chunks
                    in the collection changes. Nothing is written to disk.

    What is indexed for a chunk is the text that is also embedded: the context line
    ("Forum post by <author> on the proposal "<title>":") + the chunk, so an author's name or
    a title word in the question matches.

WHERE IT SITS
    features/chat/retrieval.py retrieve() --> THIS FILE (keyword hits)
                                          --> vector/embedding.py (vector hits), then merges both.
"""

import math
import re
from collections import Counter, defaultdict

K1 = 1.5          # how quickly repeating a word stops adding score (standard BM25 value)
B = 0.75          # how strongly long chunks are penalised (standard BM25 value)

# A word: letters and digits, keeping dots inside it so "nick.eth" and "v3.7" stay one word.
_WORD = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Lower-case words of a text. 'nick.eth' also yields 'nick', so 'nick' in a question matches."""
    words = []
    for word in _WORD.findall((text or "").lower()):
        words.append(word)
        if "." in word:
            words.extend(part for part in word.split(".") if part)
    return words


def matches(metadata: dict, where: dict | None) -> bool:
    """
    True if a chunk's metadata passes a Chroma-style filter. Supports what the chat uses:
    {"key": value}, {"key": {"$in": [...]}}, {"key": {"$eq": v}} and {"$and": [...]} / {"$or": [...]}.
    An unsupported operator raises, so a filter is never silently ignored.
    """
    if not where:
        return True
    for key, wanted in where.items():
        if key == "$and":
            if not all(matches(metadata, part) for part in wanted):
                return False
        elif key == "$or":
            if not any(matches(metadata, part) for part in wanted):
                return False
        elif isinstance(wanted, dict):
            for op, value in wanted.items():
                if op == "$in":
                    if metadata.get(key) not in value:
                        return False
                elif op == "$eq":
                    if metadata.get(key) != value:
                        return False
                elif op == "$ne":
                    if metadata.get(key) == value:
                        return False
                else:
                    raise ValueError(f"keyword index: unsupported filter operator {op!r}")
        elif metadata.get(key) != wanted:
            return False
    return True


class KeywordIndex:
    """BM25 over a fixed set of chunks. Build once, search many times."""

    def __init__(self, chunks: dict[str, tuple[str, dict]], searchable_text=None):
        """
        Parameters:
            chunks          - {chunk_id: (text, metadata)}, as vector/embedding.py indexed_documents returns.
            searchable_text - (text, metadata) -> the text to index for a chunk. Default: the text itself.
        """
        self.ids = list(chunks)
        self.texts = [chunks[i][0] for i in self.ids]
        self.metadatas = [chunks[i][1] for i in self.ids]
        searchable_text = searchable_text or (lambda text, metadata: text)
        self._lengths = []
        self._postings = defaultdict(list)                  # word -> [(chunk position, times it occurs)]
        for position, (text, metadata) in enumerate(zip(self.texts, self.metadatas)):
            words = tokenize(searchable_text(text, metadata))
            self._lengths.append(len(words))
            for word, count in Counter(words).items():
                self._postings[word].append((position, count))
        self._average_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query: str, n: int = 30, where: dict | None = None) -> list[dict]:
        """
        The n best-scoring chunks that pass `where`, best first:
        [{"id", "document", "metadata", "keyword_score"}]. Chunks sharing no word with the
        query are never returned, so the list can be shorter than n, or empty.
        """
        total = len(self.ids)
        scores = defaultdict(float)
        for word in set(tokenize(query)):
            postings = self._postings.get(word)
            if not postings:
                continue
            idf = math.log(1 + (total - len(postings) + 0.5) / (len(postings) + 0.5))
            for position, count in postings:
                length_norm = 1 - B + B * self._lengths[position] / self._average_length
                scores[position] += idf * count * (K1 + 1) / (count + K1 * length_norm)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], self.ids[item[0]]))
        hits = []
        for position, score in ranked:
            if matches(self.metadatas[position], where):
                hits.append({"id": self.ids[position], "document": self.texts[position],
                             "metadata": self.metadatas[position], "keyword_score": score})
                if len(hits) == n:
                    break
        return hits


_cached: tuple[int, KeywordIndex] | None = None          # (chunks in the collection when built, the index)


def get_keyword_index(collection=None) -> KeywordIndex:
    """
    The keyword index over the real collection. Rebuilt when the collection's chunk count
    changed since it was built (new posts were indexed). A change that keeps the count the
    same (an edited post) is picked up at the next restart.
    """
    global _cached
    from vector.embedding import embedding_text, get_collection, indexed_documents
    collection = collection if collection is not None else get_collection()
    count = collection.count()
    if _cached is None or _cached[0] != count:
        _cached = (count, KeywordIndex(indexed_documents(collection), searchable_text=embedding_text))
    return _cached[1]


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/retrieval.py, which merges these hits with the vector hits.
# To change what counts as a word: tokenize(). To support another filter: matches().
