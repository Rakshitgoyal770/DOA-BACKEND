# tests/test_self_disclosed.py
"""Which forum addresses count as the author's own wallet (Phase 1, item 4)."""

from features.identity.common import WALLET_RE
from features.identity.strategies.self_disclosed import claimed_addresses, link_self_disclosed
from features.identity.strategies.upgrade import upgrade_self_disclosed
from tests.helpers import add_identity, add_post, add_proposal, add_votes

ADDR = "0x" + "ab" * 20          # a valid 40-hex-character address
OTHER = "0x" + "cd" * 20
HASH = "0x" + "ef" * 32          # 64 hex characters: a transaction hash / proposal id


def identities(conn):
    return {r["forum_username"]: (r["wallet_address"], r["confidence_level"], r["resolution_method"])
            for r in conn.execute("SELECT * FROM resolved_identities")}


# ── the address pattern ───────────────────────────────────────────────────────

def test_wallet_pattern_ignores_longer_hashes():
    assert WALLET_RE.findall(f"wallet {ADDR}.") == [ADDR]
    assert WALLET_RE.findall(f"Hash: {HASH}") == []
    assert WALLET_RE.findall(f"https://snapshot.box/#/proposal/{HASH}") == []


# ── what counts as a claim of ownership ──────────────────────────────────────

def test_accepts_addresses_the_author_claims():
    assert claimed_addresses(f"My delegate address: {ADDR}") == [ADDR]
    assert claimed_addresses(f"my wallet is {ADDR}") == [ADDR]
    assert claimed_addresses(f"Delegate address: `{ADDR}`") == [ADDR]
    assert claimed_addresses(f"Link to Snapshot Profile: https://v1.snapshot.box/#/profile/{ADDR}") == [ADDR]


def test_rejects_addresses_that_are_not_the_authors_voting_wallet():
    # real patterns from our forum data
    assert claimed_addresses(f"to receive this grant: Yes L2 recipient address: {ADDR}") == []
    assert claimed_addresses(f"The RewardDistributor contract is deployed at {ADDR}") == []
    assert claimed_addresses(f"The GHO Risk Council multisig is {ADDR}") == []
    assert claimed_addresses(f"moved the funds to {ADDR}") == []
    assert claimed_addresses(f"my payout address: {ADDR}") == []      # "my" but not a voting wallet


# ── linking, cleanup and safety ──────────────────────────────────────────────

def test_links_a_claimed_address_as_low_confidence(db):
    add_post(db, 1, "P", "Alice", f"Hi! My delegate address: {ADDR}")
    link_self_disclosed(db)
    assert identities(db) == {"alice": (ADDR, "low", "self_disclosed")}


def test_skips_users_who_claim_two_different_addresses(db):
    add_post(db, 1, "P", "bob", f"my wallet: {ADDR}")
    add_post(db, 2, "P", "bob", f"my wallet: {OTHER}")
    link_self_disclosed(db)
    assert identities(db) == {}


def test_removes_old_links_that_fail_the_new_rule(db):
    add_post(db, 1, "P", "grantee", f"L2 recipient address: {ADDR}")
    add_identity(db, "grantee", ADDR, "low", "self_disclosed")       # made by the old rule

    result = link_self_disclosed(db)

    assert identities(db) == {}
    assert result["removed"] == 1


def test_never_touches_links_from_other_methods(db):
    add_post(db, 1, "P", "carol", f"recipient address: {ADDR}")
    add_identity(db, "carol", OTHER, "certain", "registry")

    link_self_disclosed(db)

    assert identities(db) == {"carol": (OTHER, "certain", "registry")}


def test_keeps_a_corroborated_link_at_high(db):
    add_post(db, 1, "P", "dave", f"Snapshot Profile: https://snapshot.org/#/profile/{ADDR}")
    add_identity(db, "dave", ADDR, "high", "self_disclosed")         # upgraded earlier by vote evidence

    link_self_disclosed(db)

    assert identities(db) == {"dave": (ADDR, "high", "self_disclosed")}


def test_running_twice_changes_nothing(db):
    add_post(db, 1, "P", "erin", f"my voting address is {ADDR}")
    link_self_disclosed(db)
    second = link_self_disclosed(db)
    assert (second["linked"], second["removed"]) == (0, 0)


def test_upgrade_counts_only_links_that_actually_changed(db):
    wallet = ADDR[:-1] + "0"                       # add_votes names its first voter <prefix>0
    add_proposal(db, "P", votes_count=1)
    add_votes(db, "P", 1, voter_prefix=ADDR[:-1])  # so this wallet voted in the DAO
    add_post(db, 1, "P", "frank", "hello")
    add_post(db, 2, "P", "gina", "hello")
    add_identity(db, "frank", wallet, "low", "self_disclosed")    # will be upgraded
    add_identity(db, "gina", wallet, "high", "self_disclosed")    # already high: not counted

    assert upgrade_self_disclosed(db)["upgraded"] == 1
    assert identities(db)["frank"][1] == "high"
