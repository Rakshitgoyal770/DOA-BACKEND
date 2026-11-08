# tests/test_chunking.py
"""vector/chunking.py: how text is split, and that nothing is left for the embedding model to truncate."""

import pytest

import db.schema as schema
from vector.chunking import FORUM_MAX_CHARS, MAX_TOKENS, PROPOSAL_MAX_CHARS, chunk_text
from vector.embedding import forum_documents, proposal_documents
from tests.helpers import add_post, add_proposal

real_db = pytest.mark.skipif(not schema.DB_PATH.exists(), reason="real database not present")


# ── the splitting rules ──────────────────────────────────────────────────────

def test_a_text_that_fits_is_one_unchanged_chunk():
    assert chunk_text("A short post.", 100) == ["A short post."]
    assert chunk_text("  padded  ", 100) == ["padded"]
    assert chunk_text("", 100) == [] and chunk_text(None, 100) == []


def test_paragraphs_are_packed_up_to_the_limit_and_never_cut():
    text = "\n\n".join(["alpha " * 5, "beta " * 5, "gamma " * 5])          # 3 paragraphs of 30 characters
    chunks = chunk_text(text, 70)
    assert chunks == ["alpha alpha alpha alpha alpha\n\nbeta beta beta beta beta",
                      "gamma gamma gamma gamma gamma"]
    assert all(len(c) <= 70 for c in chunks)


def test_a_forum_post_without_line_breaks_is_split_at_sentences():
    """Our HTML cleaner removes all line breaks, so stored forum posts are one long paragraph."""
    post = " ".join(f"This is sentence number {i}." for i in range(40))
    chunks = chunk_text(post, 200)
    assert len(chunks) > 3
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.endswith(".") for c in chunks)                           # every chunk ends on a sentence end
    assert " ".join(chunks) == post                                      # nothing lost, nothing added


def test_a_sentence_longer_than_the_limit_is_cut_at_words():
    chunks = chunk_text("word " * 100, 60)
    assert all(len(c) <= 60 for c in chunks) and all(not c.startswith("ord") for c in chunks)
    assert " ".join(chunks).split() == ("word " * 100).split()


def test_an_unbroken_string_is_still_cut_to_fit():
    chunks = chunk_text("a" * 1000, 100)
    assert all(len(c) <= 100 for c in chunks) and "".join(chunks) == "a" * 1000


def test_the_token_limit_splits_text_that_the_character_limit_allows():
    """A table or URL list is short in characters but long in tokens."""
    def tokens(text):                                  # pretend every 2 characters is a token
        return len(text) // 2
    text = " ".join(f"s{i}." for i in range(200))
    by_chars = chunk_text(text, 1000)
    by_tokens = chunk_text(text, 1000, count_tokens=tokens, max_tokens=100)
    assert len(by_tokens) > len(by_chars)
    assert all(tokens(c) <= 100 for c in by_tokens)


# ── what gets indexed ────────────────────────────────────────────────────────

def test_short_posts_keep_their_id_and_long_posts_get_chunk_suffixes(db):
    add_proposal(db, "P")
    add_post(db, 1, "P", "short", "A short post.")
    add_post(db, 2, "P", "long", " ".join(f"Sentence {i} is here." for i in range(300)))

    docs = forum_documents(db)

    assert "forum_post_P_1" in docs                                      # unchanged id
    long_ids = [i for i in docs if i.startswith("forum_post_P_2")]
    assert len(long_ids) > 1 and long_ids == [f"forum_post_P_2_c{n}" for n in range(len(long_ids))]
    assert all(len(docs[i][0]) <= FORUM_MAX_CHARS for i in long_ids)
    assert len({tuple(sorted(docs[i][1].items())) for i in long_ids}) == 1       # every chunk has the author's metadata
    assert docs[long_ids[0]][1]["author"] == "long"


def test_long_proposal_bodies_are_chunked_with_the_proposal_limit(db):
    add_proposal(db, "P", body="\n\n".join(f"Paragraph {i}. " + "text " * 60 for i in range(20)))
    docs = proposal_documents(db)
    assert len(docs) > 3 and all(len(t) <= PROPOSAL_MAX_CHARS for t, _ in docs.values())
    assert [i for i in docs] == [f"proposal_P_{n}" for n in range(len(docs))]


# ── the real data: nothing is left for the embedding model to truncate ───────

@real_db
def test_no_real_chunk_exceeds_the_embedding_models_limit():
    """Before chunking, 17% of forum posts were longer than 512 tokens and 46.8% of all
    forum text was invisible to search. Every chunk must now fit."""
    from vector.embedding import get_model, token_counter
    model = get_model()
    count = token_counter(model)
    conn = schema.get_connection()
    try:
        docs = {**proposal_documents(conn, count), **forum_documents(conn, count)}
    finally:
        conn.close()
    too_long = {i: count(t) for i, (t, _) in docs.items() if count(t) > model.max_seq_length}
    assert not too_long, too_long
    assert max(count(t) for t, _ in docs.values()) <= MAX_TOKENS
