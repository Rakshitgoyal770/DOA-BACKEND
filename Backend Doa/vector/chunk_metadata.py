# vector/chunk_metadata.py
"""
vector/chunk_metadata.py — The ONE definition of what metadata a search chunk carries.

WHY THIS FILE EXISTS
    Chunk metadata used to be hand-built dictionaries in two places. A misspelled key or
    a wrong type was stored without complaint and later showed up as a filter that
    silently matched nothing. Every chunk's metadata is now built through ChunkMetadata,
    which rejects unknown keys, wrong types and impossible combinations at index time.

STATIC vs DYNAMIC (the rule behind the field list)
    STATIC fields never change after a chunk exists (DAO, proposal, thread, post,
    author, dates). They are safe to FILTER on, and live here for good.
    DYNAMIC fields (resolved_wallet, confidence_level, voting_power) change when
    identity links or votes change. They are kept for now because the API reads them
    (features/chat/routes.py), but new code must read such facts from SQLite at
    question time, and a later step removes them from the index.

THE FIELDS
    every chunk    schema_version, managed_by, source_type, proposal_id, space_id, title,
                   chunk_index, chunk_count, content_hash, created_at (UTC epoch seconds)
    forum posts    author (as written), author_lower, post_id, post_number, topic_id,
                   thread_key ("<forum host>:<topic id>")
    proposal text  proposal_author (the proposer's wallet, lower case)
    dynamic        resolved_wallet, confidence_level, voting_power  (forum posts, when linked)
    A field with no value is LEFT OUT (Chroma rejects None), never stored as null.

WHERE IT SITS
    vector/embedding.py proposal_documents() / forum_documents() --> THIS FILE --> Chroma metadata
    vector/embedding.py check_index() reads stored metadata back through the same model.
"""

import hashlib
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 3          # 1 = the original keys; 2 = this schema; 3 = adds embedded_hash
MANAGED_BY = "dao-pipeline"  # stamped on every chunk we write; tells our chunks from foreign ones

# Fields that only make sense for one kind of chunk (checked by the validator below).
FORUM_ONLY = ("author", "author_lower", "post_id", "post_number", "topic_id", "thread_key",
              "resolved_wallet", "confidence_level", "voting_power")
PROPOSAL_ONLY = ("proposal_author",)


def content_hash(text: str) -> str:
    """First 16 hex characters of the SHA-256 of a chunk's text (detects an edited chunk)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def epoch_from_iso(value: str | None) -> int | None:
    """
    '2022-07-24T19:46:54.605Z' -> 1658692014 (UTC epoch seconds), or None if missing or unreadable.

    Parameter (where it comes from): forum_posts.created_at, as Discourse writes it.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def thread_key(discussion_url: str | None, topic_id: int | None) -> str | None:
    """
    'gov.optimism.io:1234' from a proposal's forum link and a post's topic id, or None.
    Topic ids are only unique inside one forum, so the host is part of the key.

    Parameters (where they come from): proposals.discussion_url and forum_posts.topic_id.
    """
    if not discussion_url or topic_id is None or not discussion_url.lower().startswith(("http://", "https://")):
        return None
    host = (urlparse(discussion_url).hostname or "").lower()
    return f"{host}:{topic_id}" if host else None


class ChunkMetadata(BaseModel):
    """The metadata of one chunk. Build it, then call to_chroma() for the dictionary to store."""

    model_config = ConfigDict(extra="forbid")          # an unknown key is an error, not a silent extra

    # every chunk
    schema_version: int = SCHEMA_VERSION
    managed_by: Literal["dao-pipeline"] = MANAGED_BY
    source_type: Literal["proposal_body", "forum_post"]
    proposal_id: str = Field(min_length=1)
    space_id: str | None = None
    title: str | None = None
    chunk_index: int = Field(ge=0)
    chunk_count: int = Field(ge=1)
    content_hash: str = Field(min_length=16, max_length=16)
    # Hash of the text that was EMBEDDED (a context line + the chunk, see vector/embedding.py
    # embedding_text). The sync re-embeds a chunk when this changes, e.g. after a title edit.
    embedded_hash: str | None = Field(default=None, min_length=16, max_length=16)
    created_at: int | None = None

    # forum posts
    author: str | None = None
    author_lower: str | None = None
    post_id: int | None = None
    post_number: int | None = None
    topic_id: int | None = None
    thread_key: str | None = None

    # proposal text
    proposal_author: str | None = None

    # dynamic (transitional, see the module docstring)
    resolved_wallet: str | None = None
    confidence_level: Literal["certain", "high", "medium", "low", "unresolved"] | None = None
    voting_power: float | None = None

    @model_validator(mode="after")
    def _check_combination(self):
        if self.chunk_index >= self.chunk_count:
            raise ValueError(f"chunk_index {self.chunk_index} must be below chunk_count {self.chunk_count}")
        wrong_kind = PROPOSAL_ONLY if self.source_type == "forum_post" else FORUM_ONLY
        present = [name for name in wrong_kind if getattr(self, name) is not None]
        if present:
            raise ValueError(f"{present} do not belong on a {self.source_type} chunk")
        if self.source_type == "forum_post":
            if not self.author or self.post_id is None:
                raise ValueError("a forum_post chunk needs author and post_id")
            if self.author_lower != self.author.lower():
                raise ValueError("author_lower must be the lower-case form of author")
            if self.resolved_wallet and not self.confidence_level:
                raise ValueError("a resolved_wallet needs its confidence_level")
            if self.voting_power is not None and not self.resolved_wallet:
                raise ValueError("voting_power needs a resolved_wallet")
        return self

    def to_chroma(self) -> dict:
        """The dictionary to store in Chroma: fields without a value are left out."""
        return self.model_dump(exclude_none=True)


# ── Where control goes next ───────────────────────────────────────────────────
# Back to vector/embedding.py, which builds one ChunkMetadata per chunk, stores
# to_chroma(), and later reads stored metadata back through this model in check_index().
# To add a field: add it here, set it in embedding.py, bump SCHEMA_VERSION, and add a
#   test in tests/test_chunk_metadata.py. The next sync updates the metadata only (no
#   re-embedding), because the chunk text did not change.
