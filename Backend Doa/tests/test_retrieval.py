# tests/test_retrieval.py
"""features/chat/retrieval.py (vector + keyword search, merged) and vector/keyword_index.py.

An in-memory Chroma collection and a tiny fake model: no model download, no real index."""

import uuid

import chromadb
import pytest

from features.chat.retrieval import fuse, retrieve
from vector.embedding import QUERY_PREFIX
from vector.keyword_index import KeywordIndex, matches, tokenize

# The fake model puts a text on one of three axes by the topic word it contains.
AXES = {"treasury": [1.0, 0.0, 0.0], "audit": [0.0, 1.0, 0.0], "election": [0.0, 0.0, 1.0]}


class FakeModel:
    def __init__(self):
        self.asked = []

    def encode(self, text):
        self.asked.append(text)
        return next((vector for word, vector in AXES.items() if word in text.lower()), [0.6, 0.6, 0.6])


CHUNKS = {
    "t1": ("We should diversify the treasury into stablecoins.", {"proposal_id": "P1", "space_id": "A", "author_lower": "kpk", "source_type": "forum_post"}),
    "t2": ("The treasury is too exposed to ETH, in my view.", {"proposal_id": "P2", "space_id": "B", "author_lower": "ann", "source_type": "forum_post"}),
    "a1": ("The audit by Sherlock found two issues in syrupUSDC.", {"proposal_id": "P1", "space_id": "A", "author_lower": "ann", "source_type": "forum_post"}),
    "e1": ("Candidates for the election must apply by Friday.", {"proposal_id": "P2", "space_id": "B", "author_lower": "kpk", "source_type": "proposal_body"}),
}


@pytest.fixture
def collection():
    col = chromadb.EphemeralClient().get_or_create_collection(f"test_{uuid.uuid4().hex}")
    model = FakeModel()
    col.add(ids=list(CHUNKS), documents=[t for t, _ in CHUNKS.values()], metadatas=[m for _, m in CHUNKS.values()],
            embeddings=[model.encode(t) for t, _ in CHUNKS.values()])
    return col


def search(collection, query, **kw):
    kw.setdefault("max_distance", 10)
    kw.setdefault("reranker", False)                 # the merged order; the reranker has its own tests below
    return retrieve(query, collection=collection, model=FakeModel(), keyword_index=KeywordIndex(CHUNKS), **kw)


# ── words and filters ─────────────────────────────────────────────────────────

def test_words_keep_dotted_names_whole_and_also_split_them():
    assert tokenize("What did Nick.eth say about v3.7?") == ["what", "did", "nick.eth", "nick", "eth", "say", "about", "v3.7", "v3", "7"]
    assert tokenize(None) == []


def test_the_keyword_filter_understands_the_filters_the_chat_uses():
    meta = {"proposal_id": "P1", "space_id": "A", "source_type": "forum_post"}
    assert matches(meta, None) and matches(meta, {"proposal_id": "P1"}) and not matches(meta, {"proposal_id": "P2"})
    assert matches(meta, {"proposal_id": {"$in": ["P1", "P9"]}}) and not matches(meta, {"proposal_id": {"$in": ["P9"]}})
    assert matches(meta, {"$and": [{"space_id": "A"}, {"source_type": "forum_post"}]})
    assert not matches(meta, {"$and": [{"space_id": "A"}, {"source_type": "proposal_body"}]})
    assert matches(meta, {"$or": [{"space_id": "Z"}, {"space_id": "A"}]})
    assert not matches(meta, {"author_lower": "kpk"})                    # a missing key never matches
    with pytest.raises(ValueError):
        matches(meta, {"created_at": {"$gt": 5}})                        # never silently ignored


# ── keyword search ────────────────────────────────────────────────────────────

def test_a_rare_exact_word_finds_its_chunk_and_unrelated_chunks_are_not_returned():
    hits = KeywordIndex(CHUNKS).search("What did Sherlock say about syrupUSDC?")
    assert hits[0]["id"] == "a1" and hits[0]["keyword_score"] > 0
    assert "e1" not in [h["id"] for h in hits]                           # shares no word with the question
    assert KeywordIndex(CHUNKS).search("zzz qqq") == []


def test_keyword_search_respects_the_filter_and_n():
    index = KeywordIndex(CHUNKS)
    assert [h["id"] for h in index.search("treasury", where={"space_id": "B"})] == ["t2"]
    assert len(index.search("the treasury", n=1)) == 1
    assert len(index) == 4


def test_the_indexed_text_can_carry_the_author_so_a_name_in_the_question_matches():
    by_author = KeywordIndex(CHUNKS, searchable_text=lambda text, meta: f"Forum post by {meta['author_lower']}:\n{text}")
    assert {h["id"] for h in by_author.search("what did kpk say")} == {"t1", "e1"}
    assert KeywordIndex(CHUNKS).search("kpk") == []                      # the plain chunk never names its author
    assert by_author.search("kpk")[0]["document"] == CHUNKS[by_author.search("kpk")[0]["id"]][0]   # stored text is plain


# ── merging ───────────────────────────────────────────────────────────────────

def test_fusion_puts_a_chunk_both_searches_found_above_one_found_by_a_single_search():
    scores = fuse([["a", "b", "c"], ["c", "a", "d"]])
    assert sorted(scores, key=scores.get, reverse=True) == ["a", "c", "b", "d"]
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62) and scores["d"] == pytest.approx(1 / 63)


def test_a_question_is_embedded_with_the_instruction_prefix(collection):
    model = FakeModel()
    retrieve("treasury?", collection=collection, model=model, keyword_index=KeywordIndex(CHUNKS), max_distance=10,
             reranker=False)
    assert model.asked == [QUERY_PREFIX + "treasury?"]


def test_meaning_and_keywords_are_merged(collection):
    """'audit' puts the question next to a1 by meaning; the exact word 'ETH' brings in t2 by keyword."""
    found = search(collection, "audit findings on syrupUSDC and ETH", n_results=4)
    by_id = {c["id"]: c for c in found}
    assert found[0]["id"] == "a1" and set(by_id["a1"]["found_by"]) == {"vector", "keyword"}
    assert "keyword" in by_id["t2"]["found_by"]
    assert [c["score"] for c in found] == sorted((c["score"] for c in found), reverse=True)
    assert all({"id", "document", "metadata", "distance", "score", "found_by"} <= set(c) for c in found)


def test_a_chunk_only_the_keyword_search_found_still_gets_its_real_distance(collection):
    class OnlyE1:                                                         # a keyword index that returns one far chunk
        def search(self, query, n, where):
            return [{"id": "e1", "document": CHUNKS["e1"][0], "metadata": CHUNKS["e1"][1], "keyword_score": 9.0}]
    found = retrieve("treasury", collection=collection, model=FakeModel(), keyword_index=OnlyE1(), max_distance=10,
                     reranker=False)
    e1 = next(c for c in found if c["id"] == "e1")
    assert e1["distance"] == pytest.approx(2.0)                           # [1,0,0] vs [0,0,1], squared L2 as Chroma reports it


def test_the_distance_cutoff_drops_far_chunks_even_when_keywords_match(collection):
    """The question is about the treasury by meaning; e1 matches the word 'election' but is far away."""
    assert "e1" in [c["id"] for c in search(collection, "treasury election", n_results=8)]
    close = search(collection, "treasury election", max_distance=0.5, n_results=8)
    assert sorted(c["id"] for c in close) == ["t1", "t2"] and all(c["distance"] <= 0.5 for c in close)


def test_the_filter_applies_to_both_searches(collection):
    found = search(collection, "the treasury audit election", where={"space_id": "B"}, n_results=8)
    assert {c["id"] for c in found} == {"t2", "e1"}
    scoped = search(collection, "treasury", where={"$and": [{"space_id": "A"}, {"author_lower": "kpk"}]}, n_results=8)
    assert [c["id"] for c in scoped] == ["t1"]


def test_n_results_caps_the_list_and_nothing_found_is_an_empty_list(collection):
    assert len(search(collection, "the treasury audit election", n_results=2)) == 2
    assert search(collection, "treasury", where={"space_id": "nobody"}) == []


def test_a_chunk_deleted_after_the_keyword_index_was_built_is_skipped(collection):
    collection.delete(ids=["t2"])
    assert "t2" not in [c["id"] for c in search(collection, "treasury", n_results=8)]


# ── reranking ─────────────────────────────────────────────────────────────────

class PrefersElections:
    """A reranker that scores a passage by whether it mentions the election, and records what it read."""

    def __init__(self):
        self.pairs = []

    def predict(self, pairs, batch_size=None, show_progress_bar=None):
        self.pairs.extend(pairs)
        return [5.0 if "election" in text else 0.0 for _, text in pairs]


def test_the_reranker_reorders_the_merged_candidates(collection):
    merged = [c["id"] for c in search(collection, "the treasury election", n_results=8)]
    reranker = PrefersElections()
    found = search(collection, "the treasury election", n_results=8, reranker=reranker)
    assert merged[0] != "e1" and found[0]["id"] == "e1" and found[0]["rerank_score"] == 5.0
    assert [c["id"] for c in found[1:]] == [i for i in merged if i != "e1"]          # ties keep the merged order
    assert sorted(c["id"] for c in found) == sorted(merged)                          # nothing added, nothing lost


def test_the_reranker_reads_the_question_with_the_context_line_and_the_chunk(collection):
    with_author = {"t1": (CHUNKS["t1"][0], {**CHUNKS["t1"][1], "author": "kpk", "title": "Diversify"})}
    reranker = PrefersElections()
    retrieve("treasury?", collection=collection, model=FakeModel(), keyword_index=KeywordIndex(with_author),
             where={"author_lower": "kpk"}, max_distance=0.5, reranker=reranker)
    assert [question for question, _ in reranker.pairs] == ["treasury?"]
    text = reranker.pairs[0][1]
    assert text.startswith("Forum post by ") and text.endswith(CHUNKS["t1"][0])


def test_chunks_beyond_the_distance_cutoff_never_reach_the_reranker(collection):
    reranker = PrefersElections()
    found = search(collection, "treasury election", max_distance=0.5, n_results=8, reranker=reranker)
    assert sorted(c["id"] for c in found) == ["t1", "t2"]
    assert all("election" not in text for _, text in reranker.pairs)


def test_without_a_reranker_model_the_merged_order_is_kept(monkeypatch):
    import vector.reranker as reranker_module
    monkeypatch.setattr(reranker_module, "get_reranker", lambda: None)
    candidates = [{"id": "a", "document": "x"}, {"id": "b", "document": "y"}]
    assert reranker_module.rerank("q", candidates) == candidates and "rerank_score" not in candidates[0]
    assert reranker_module.rerank("q", []) == []
