# tests/test_embedding_sync.py
"""The incremental index sync in vector/embedding.py (Phase 1, item 3).

Uses an in-memory Chroma collection and a fake model, so no model download
and no change to the real chroma_data/ index."""

import uuid

import chromadb
import pytest

from vector.embedding import same_metadata, sync_index
from tests.helpers import add_identity, add_post, add_proposal, add_votes

WALLET = "0xAbCdEf" + "0" * 34      # mixed case, as Snapshot writes it; ends in "0" for add_votes


class FakeModel:
    """Turns each text into a tiny vector and remembers what it was asked to embed."""

    def __init__(self):
        self.encoded = []

    def encode(self, texts, batch_size=None):
        self.encoded.extend(texts)
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class ModelMustNotBeUsed:
    def encode(self, *_, **__):
        raise AssertionError("nothing changed, so nothing should be embedded")


@pytest.fixture
def collection():
    return chromadb.EphemeralClient().get_or_create_collection(f"test_{uuid.uuid4().hex}")


@pytest.fixture
def small_db(db):
    add_proposal(db, "P1", body="First paragraph.\n\nSecond paragraph.")
    add_post(db, 10, "P1", "alice", "I support this.")
    add_post(db, 11, "P1", "bob", "I am against it.")
    add_post(db, 12, "P1", "empty_user", "")            # empty posts are not indexed
    return db


def post_doc(post_id, proposal_id="P1"):
    return f"forum_post_{proposal_id}_{post_id}"


def stored(collection, doc_id):
    got = collection.get(ids=[doc_id], include=["documents", "metadatas"])
    return (got["documents"][0], got["metadatas"][0]) if got["ids"] else None


def test_first_sync_embeds_everything(small_db, collection):
    model = FakeModel()
    result = sync_index(small_db, collection=collection, model=model)

    assert result["embed"] == 3                         # 1 proposal chunk + 2 non-empty posts
    assert collection.count() == 3
    assert sorted(model.encoded) == sorted(["First paragraph.\n\nSecond paragraph.",
                                            "I support this.", "I am against it."])


def test_second_sync_does_no_work(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    result = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())
    assert (result["embed"], result["update_metadata"], result["delete"], result["unchanged"]) == (0, 0, 0, 3)


def test_only_changed_text_is_re_embedded(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    small_db.execute("UPDATE forum_posts SET content = 'Edited: I now support it.' WHERE id = 11")

    model = FakeModel()
    result = sync_index(small_db, collection=collection, model=model)

    assert model.encoded == ["Edited: I now support it."]
    assert result["embed"] == 1
    assert stored(collection, post_doc(11))[0] == "Edited: I now support it."


def test_new_identity_link_is_a_metadata_update_with_case_insensitive_vote_match(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    # Snapshot stores the voter in mixed case, the identity link is lower case
    add_votes(small_db, "P1", 1, voter_prefix=WALLET[:-1], vp=1234.5)        # voter == WALLET
    add_identity(small_db, "alice", WALLET.lower(), "high")

    result = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())

    assert (result["embed"], result["update_metadata"]) == (0, 1)
    metadata = stored(collection, post_doc(10))[1]
    assert metadata["resolved_wallet"] == WALLET.lower()
    assert metadata["voting_power"] == 1234.5


@pytest.mark.parametrize("also_edit_text", [False, True], ids=["metadata-only", "text-and-metadata"])
def test_removed_identity_link_removes_the_wallet_fields(small_db, collection, also_edit_text):
    """Chroma merges metadata, so dropped fields must be deleted explicitly.
    (Found on real data: 282 posts kept a wallet link that no longer existed.)"""
    add_identity(small_db, "alice", WALLET, "low")
    sync_index(small_db, collection=collection, model=FakeModel())
    assert "resolved_wallet" in stored(collection, post_doc(10))[1]

    small_db.execute("DELETE FROM resolved_identities WHERE forum_username = 'alice'")
    if also_edit_text:
        small_db.execute("UPDATE forum_posts SET content = 'Edited.' WHERE id = 10")
    sync_index(small_db, collection=collection, model=FakeModel())

    metadata = stored(collection, post_doc(10))[1]
    assert "resolved_wallet" not in metadata and "confidence_level" not in metadata
    again = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())
    assert (again["embed"], again["update_metadata"]) == (0, 0)


def test_removed_post_is_deleted_but_foreign_ids_are_kept(small_db, collection):
    sync_index(small_db, collection=collection, model=FakeModel())
    collection.add(ids=["manual_test_doc"], documents=["added by hand"], embeddings=[[1.0, 0.0, 0.0]])
    small_db.execute("DELETE FROM forum_posts WHERE id = 11")

    result = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed())

    assert result["delete"] == 1
    assert stored(collection, post_doc(11)) is None
    assert stored(collection, "manual_test_doc") is not None


def test_dry_run_writes_nothing(small_db, collection):
    result = sync_index(small_db, collection=collection, model=ModelMustNotBeUsed(), dry_run=True)
    assert result["embed"] == 3
    assert collection.count() == 0


def test_float_round_trip_noise_is_not_a_change():
    a = {"voting_power": 95848.83524269493, "author": "x"}
    assert same_metadata(a, {"voting_power": 95848.83524269491, "author": "x"})
    assert not same_metadata(a, {"voting_power": 95848.9, "author": "x"})
    assert not same_metadata(a, {"voting_power": 95848.83524269493})      # a key is missing
