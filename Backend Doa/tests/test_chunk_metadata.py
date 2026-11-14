# tests/test_chunk_metadata.py
"""The chunk metadata schema (vector/chunk_metadata.py) and how vector/embedding.py uses it.

Uses an in-memory Chroma collection and a fake model: no model download, and the real
chroma_data/ index is never touched."""

import uuid

import chromadb
import pytest
from pydantic import ValidationError

from tests.helpers import add_identity, add_post, add_proposal, add_votes
from vector.chunk_metadata import (MANAGED_BY, SCHEMA_VERSION, ChunkMetadata, content_hash,
                                   epoch_from_iso, thread_key)
from vector.embedding import (check_index, forum_documents, indexed_documents, proposal_documents,
                              same_metadata, sync_index)

WALLET = "0xAbCdEf" + "0" * 34
POST_TIME = "2022-07-24T19:46:54.605Z"            # 1658692014 in UTC epoch seconds


class FakeModel:
    def __init__(self):
        self.encoded = []

    def encode(self, texts, batch_size=None):
        self.encoded.extend(texts)
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class ModelMustNotBeUsed:
    def encode(self, *_, **__):
        raise AssertionError("only metadata changed, so nothing should be embedded")


@pytest.fixture
def collection():
    return chromadb.EphemeralClient().get_or_create_collection(f"test_{uuid.uuid4().hex}")


@pytest.fixture
def small_db(db):
    add_proposal(db, "P1", space_id="ens.eth", title="Fund the thing", body="First paragraph.\n\nSecond paragraph.",
                 discussion_url="https://Discuss.Example.org/t/some-thread/77")
    db.execute("UPDATE proposals SET created_ts = 1700000123, author = '0xABCDEFabcdef0000000000000000000000000001' "
               "WHERE id = 'P1'")
    add_post(db, 10, "P1", "Alice", "I support this.")
    db.execute("UPDATE forum_posts SET topic_id = 77, post_number = 3, created_at = ? WHERE id = 10", (POST_TIME,))
    add_post(db, 11, "P1", "bob", "I am against it.")
    db.commit()
    return db


# ── the model itself ──────────────────────────────────────────────────────────

def forum_kwargs(**over):
    base = dict(source_type="forum_post", proposal_id="P1", chunk_index=0, chunk_count=1,
                content_hash=content_hash("x"), author="Alice", author_lower="alice", post_id=10)
    return {**base, **over}


def test_a_valid_forum_chunk_builds_and_drops_empty_fields():
    stored = ChunkMetadata(**forum_kwargs()).to_chroma()
    assert stored["schema_version"] == SCHEMA_VERSION and stored["managed_by"] == MANAGED_BY
    assert "space_id" not in stored and "voting_power" not in stored       # None is never stored
    assert None not in stored.values()


@pytest.mark.parametrize("change, why", [
    ({"autor": "typo"}, "unknown key"),
    ({"post_id": "ten"}, "wrong type"),
    ({"chunk_index": 1}, "chunk_index must be below chunk_count"),
    ({"source_type": "tweet"}, "unknown source type"),
    ({"author_lower": "ALICE"}, "author_lower must be lower case of author"),
    ({"author": None, "author_lower": None}, "forum chunk without an author"),
    ({"proposal_author": "0xabc"}, "proposal-only field on a forum chunk"),
    ({"voting_power": 5.0}, "voting power without a wallet"),
    ({"resolved_wallet": WALLET}, "wallet without its confidence"),
    ({"confidence_level": "sure", "resolved_wallet": WALLET}, "unknown confidence"),
    ({"content_hash": "short"}, "hash must be 16 characters"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_the_model_rejects_bad_metadata(change, why):
    with pytest.raises(ValidationError):
        ChunkMetadata(**forum_kwargs(**change))


def test_a_proposal_chunk_cannot_carry_forum_fields():
    ok = dict(source_type="proposal_body", proposal_id="P1", chunk_index=0, chunk_count=2,
              content_hash=content_hash("t"))
    ChunkMetadata(**ok)
    with pytest.raises(ValidationError):
        ChunkMetadata(**ok, author="x", author_lower="x", post_id=1)


def test_helpers():
    assert epoch_from_iso(POST_TIME) == 1658692014
    assert epoch_from_iso("2022-07-24T19:46:54+00:00") == 1658692014
    assert epoch_from_iso(None) is None and epoch_from_iso("not a date") is None
    assert thread_key("https://Discuss.Example.org/t/x/77", 77) == "discuss.example.org:77"
    assert thread_key("https://gov.optimism.io/t/x/9", None) is None
    assert thread_key(None, 5) is None and thread_key("not a link", 5) is None
    assert content_hash("a") == content_hash("a") != content_hash("b") and len(content_hash("a")) == 16


# ── what the index builders produce ───────────────────────────────────────────

def test_forum_chunk_carries_every_static_field(small_db):
    meta = forum_documents(small_db)["forum_post_P1_10"][1]
    assert meta == {
        "schema_version": SCHEMA_VERSION, "managed_by": MANAGED_BY, "source_type": "forum_post",
        "proposal_id": "P1", "space_id": "ens.eth", "title": "Fund the thing",
        "chunk_index": 0, "chunk_count": 1, "content_hash": content_hash("I support this."),
        "created_at": 1658692014, "author": "Alice", "author_lower": "alice", "post_id": 10,
        "post_number": 3, "topic_id": 77, "thread_key": "discuss.example.org:77",
        "embedded_hash": content_hash('Forum post by Alice on the proposal "Fund the thing":\nI support this.'),
    }


def test_forum_chunk_without_optional_data_just_omits_those_keys(small_db):
    meta = forum_documents(small_db)["forum_post_P1_11"][1]      # no topic, number or date stored
    assert {"post_number", "topic_id", "thread_key", "created_at"}.isdisjoint(meta)
    assert meta["author_lower"] == "bob" and meta["space_id"] == "ens.eth"


def test_proposal_chunk_carries_its_static_fields(small_db):
    meta = proposal_documents(small_db)["proposal_P1_0"][1]
    assert meta == {
        "schema_version": SCHEMA_VERSION, "managed_by": MANAGED_BY, "source_type": "proposal_body",
        "proposal_id": "P1", "space_id": "ens.eth", "title": "Fund the thing", "chunk_index": 0,
        "chunk_count": 1, "content_hash": content_hash("First paragraph.\n\nSecond paragraph."),
        "created_at": 1700000123, "proposal_author": "0xabcdefabcdef0000000000000000000000000001",
        "embedded_hash": content_hash('Text of the proposal "Fund the thing":\nFirst paragraph.\n\nSecond paragraph.'),
    }


def test_the_dynamic_wallet_fields_are_still_there_and_valid(small_db):
    add_votes(small_db, "P1", 1, voter_prefix=WALLET[:-1], vp=1234.5)
    add_identity(small_db, "alice", WALLET.lower(), "high")
    meta = forum_documents(small_db)["forum_post_P1_10"][1]
    assert (meta["resolved_wallet"], meta["confidence_level"], meta["voting_power"]) == (WALLET.lower(), "high", 1234.5)
    ChunkMetadata(**meta)                                            # and the whole thing passes the schema


def test_a_long_post_keeps_one_post_id_and_numbers_its_chunks(small_db):
    sentences = " ".join(f"This is sentence number {i} of a long post." for i in range(80))
    add_post(small_db, 12, "P1", "carol", sentences)
    docs = {k: v for k, v in forum_documents(small_db).items() if k.startswith("forum_post_P1_12")}
    assert len(docs) > 1
    metas = [docs[f"forum_post_P1_12_c{i}"][1] for i in range(len(docs))]       # ids did not change
    assert [m["chunk_index"] for m in metas] == list(range(len(docs)))
    assert {m["chunk_count"] for m in metas} == {len(docs)} and {m["post_id"] for m in metas} == {12}
    assert len({m["content_hash"] for m in metas}) == len(docs)


# ── syncing: upgrade of an old index ──────────────────────────────────────────

def old_style_index(small_db, collection):
    """An index as it was before this change: the same texts and ids, the old three-key metadata."""
    model = FakeModel()
    for doc_id, (text, meta) in {**proposal_documents(small_db), **forum_documents(small_db)}.items():
        old = {k: meta[k] for k in ("source_type", "proposal_id", "author", "space_id", "title") if k in meta}
        collection.add(ids=[doc_id], documents=[text], embeddings=model.encode([text]), metadatas=[old])


def test_upgrading_an_old_index_re_embeds_every_chunk_once_and_keeps_the_stored_text(small_db, collection):
    """An index from before the context line has no embedded_hash: each chunk is embedded again, with the line."""
    old_style_index(small_db, collection)
    before = collection.get(include=["documents"])
    model = FakeModel()

    result = sync_index(small_db, collection=collection, model=model)

    assert (result["embed"], result["update_metadata"], result["delete"], result["unchanged"]) == (3, 0, 0, 0)
    assert all(text.startswith(("Forum post by ", "Text of the proposal ")) for text in model.encoded)
    after = collection.get(include=["documents"])
    assert dict(zip(after["ids"], after["documents"])) == dict(zip(before["ids"], before["documents"]))
    assert check_index(collection)["valid"] == 3


def test_after_the_upgrade_a_second_sync_does_nothing(small_db, collection):
    old_style_index(small_db, collection)
    sync_index(small_db, collection=collection, model=FakeModel())
    again = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())
    assert (again["embed"], again["update_metadata"], again["delete"], again["foreign"]) == (0, 0, 0, 0)


def test_the_stored_metadata_matches_what_the_builders_say(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    stored = indexed_documents(collection)
    wanted = {**proposal_documents(small_db), **forum_documents(small_db)}
    assert stored.keys() == wanted.keys()
    assert all(same_metadata(stored[i][1], wanted[i][1]) for i in wanted)


# ── foreign documents ─────────────────────────────────────────────────────────

def test_a_foreign_document_is_reported_but_kept_unless_asked(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    collection.add(ids=["zeptimus_post_1"], documents=["added by hand"], embeddings=[[1.0, 0.0, 0.0]],
                   metadatas=[{"source_type": "forum_post", "proposal_id": "P1", "author": "Z"}])

    kept = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())
    assert (kept["foreign"], kept["delete"], kept["foreign_ids"]) == (1, 0, ["zeptimus_post_1"])
    assert collection.count() == 4

    removed = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed(), remove_foreign=True)
    assert removed["delete"] == 1 and collection.count() == 3


def test_dry_run_with_remove_foreign_deletes_nothing(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    collection.add(ids=["stray"], documents=["x"], embeddings=[[1.0, 0.0, 0.0]])
    sync_index(small_db, collection=collection, model=ModelMustNotBeUsed(), dry_run=True, remove_foreign=True)
    assert collection.count() == 4


def test_a_stamped_chunk_that_sql_no_longer_wants_is_deleted_even_without_our_prefix(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    meta = forum_documents(small_db)["forum_post_P1_10"][1]
    collection.add(ids=["renamed_scheme_1"], documents=["old"], embeddings=[[1.0, 0.0, 0.0]], metadatas=[meta])
    result = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())
    assert result["delete"] == 1 and result["foreign"] == 0


# ── check_index ───────────────────────────────────────────────────────────────

def test_check_index_counts_valid_legacy_foreign_and_invalid(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    collection.add(ids=["forum_post_P1_99"], documents=["legacy"], embeddings=[[1.0, 0.0, 0.0]],
                   metadatas=[{"source_type": "forum_post", "proposal_id": "P1", "author": "x"}])
    collection.add(ids=["stray"], documents=["x"], embeddings=[[1.0, 0.0, 0.0]])
    collection.add(ids=["forum_post_P1_98"], documents=["bad"], embeddings=[[1.0, 0.0, 0.0]],
                   metadatas=[{"managed_by": MANAGED_BY, "source_type": "forum_post", "proposal_id": "P1"}])

    report = check_index(collection)

    assert (report["total"], report["valid"], report["legacy"], report["foreign"], report["invalid"]) == (6, 3, 1, 1, 1)
    assert report["foreign_ids"] == ["stray"] and report["invalid_examples"][0]["id"] == "forum_post_P1_98"


# ── what is embedded: a context line + the chunk ──────────────────────────────

def test_the_context_line_names_the_author_and_the_proposal():
    from vector.embedding import context_header
    assert context_header("forum_post", "Fund the thing", "Alice") == 'Forum post by Alice on the proposal "Fund the thing":\n'
    assert context_header("proposal_body", "Fund the thing") == 'Text of the proposal "Fund the thing":\n'
    assert context_header("forum_post", None, None) == "Forum post by unknown on a proposal:\n"


def test_a_long_title_is_shortened_then_dropped_so_the_chunk_itself_is_never_cut():
    from vector.embedding import MODEL_MAX_TOKENS, embedding_text

    def words(text):                                             # pretend one word is one token
        return len(text.split())
    title = " ".join(f"t{i}" for i in range(20))
    meta = {"source_type": "forum_post", "title": title, "author": "bob"}
    assert embedding_text("word " * 10, meta, words).startswith(f'Forum post by bob on the proposal "{title}":')
    nearly_full = "word " * (MODEL_MAX_TOKENS - 20)              # the full title (20 words) no longer fits
    cut = embedding_text(nearly_full, meta, words)
    assert '"t0 t1 t2 t3 t4 t5 t6 t7 ..."' in cut and words(cut) <= MODEL_MAX_TOKENS
    full = "word " * (MODEL_MAX_TOKENS - 8)                      # not even the short title fits
    assert embedding_text(full, meta, words).startswith("Forum post by bob on a proposal:")
    whole = "word " * (MODEL_MAX_TOKENS - 2)                     # the chunk fills the limit on its own
    assert embedding_text(whole, meta, words) == whole           # no line at all: the model fails on a longer text
    assert all(words(embedding_text("word " * n, meta, words)) <= MODEL_MAX_TOKENS for n in range(470, MODEL_MAX_TOKENS + 1))
    assert embedding_text(nearly_full, meta, None).count("t19") == 1        # no tokenizer: never shortened


def test_a_changed_title_re_embeds_the_proposals_chunks_and_nothing_else(small_db, collection):
    add_proposal(small_db, "P2", space_id="ens.eth", title="Other", body="Other body.")
    sync_index(small_db, collection=collection, model=FakeModel())
    small_db.execute("UPDATE proposals SET title = 'Fund the other thing' WHERE id = 'P1'")
    model = FakeModel()
    result = sync_index(small_db, collection=collection, model=model)
    assert (result["embed"], result["unchanged"]) == (3, 1)      # P1's body chunk and its 2 posts; P2 untouched
    assert all('"Fund the other thing"' in text for text in model.encoded)


def test_a_question_is_encoded_with_the_models_instruction_in_front():
    from vector.embedding import QUERY_PREFIX, encode_query

    class Recorder:
        def encode(self, text):
            self.text = text
            return [1, 2]
    model = Recorder()
    assert encode_query(model, "Why?") == [1.0, 2.0] and model.text == QUERY_PREFIX + "Why?"
