# tests/test_metrics.py
"""features/metrics.py: each governance number has one definition, and every
place that reports it (DAO endpoints, proposal endpoints, chat) agrees."""

import json

from features.chat.context import proposal_facts
from features.daos.service import compute_dao_stats, top_proposals
from features.metrics import (choice_text, count_forum_posters, decode_choice, silence_ratio_pct,
                              top_voter_share, winning_share_pct)
from features.proposals.service import concentration, list_proposals
from tests.helpers import add_post, add_proposal, add_votes

CHOICES = ["For", "Against", "Abstain"]


# ── choice names ──────────────────────────────────────────────────────────────

def test_decode_choice_keeps_the_shape_and_uses_names():
    assert decode_choice("1", CHOICES) == "For"
    assert decode_choice("[2, 1]", CHOICES) == ["Against", "For"]            # ranked: order kept
    assert decode_choice('{"1": 2, "3": 1}', CHOICES) == {"For": 2, "Abstain": 1}
    assert decode_choice("7", CHOICES) == 7                                 # unknown number kept
    assert decode_choice(None, CHOICES) is None


def test_choice_text_for_the_prompt():
    assert choice_text("For") == "For"
    assert choice_text(["Against", "For"]) == "Against, For"
    assert choice_text({"For": 2, "Abstain": 1}) == "For: 2, Abstain: 1"


# ── percentages ───────────────────────────────────────────────────────────────

def test_silence_ratio_rounding_and_no_voters():
    assert silence_ratio_pct(17, 63_845) == 0.027
    assert silence_ratio_pct(1, 3, decimals=None) == 100 / 3        # unrounded, for averages
    assert silence_ratio_pct(5, 0) is None


def test_winning_share():
    assert winning_share_pct("[1500.0, 20.0, 480.0]", 2000.0) == 75.0
    assert winning_share_pct(None, 2000.0) is None
    assert winning_share_pct("[1, 2]", 0) is None


# ── one poster rule everywhere (the old copies disagreed on upper/lower case) ─

def test_alice_and_ALICE_are_one_poster_in_every_report(db):
    add_proposal(db, "P", space_id="dao.eth", votes_count=10, scores=[7, 3])
    add_post(db, 1, "P", "Alice", "first")
    add_post(db, 2, "P", "alice", "second")
    add_post(db, 3, "P", "bob", "third")

    assert count_forum_posters(db, "P") == 2
    assert list_proposals(db, None, None, 10, 0)[0]["forum_posters"] == 2
    assert top_proposals(db, "dao.eth")[0]["forum_posters"] == 2
    assert proposal_facts(db, "P")["forum_posters"] == 2
    # and therefore the same silence ratio from the DAO stats and the chat facts
    assert compute_dao_stats(db, "dao.eth")["avg_silence_ratio_pct"] == proposal_facts(db, "P")["silence_ratio_pct"] == 20.0


# ── top-voter share: one function for the endpoint and the chat ──────────────

def test_top_voter_share_complete_data(db):
    add_proposal(db, "P", votes_count=5, choices=CHOICES, scores=[10, 0, 0])
    add_votes(db, "P", 5, vp=2.0)
    r = top_voter_share(db, "P", top_n=2)
    assert (r["stored_votes"], r["partial"], r["top_n_share_pct"]) == (5, False, 40.0)
    assert r["top_voters"][0]["choice"] == "For"


def test_top_voter_share_with_partial_data_uses_the_full_tally(db):
    # 2 of 10 votes stored; Snapshot's total voting power is 100
    add_proposal(db, "P", votes_count=10, scores=[100, 0])
    add_votes(db, "P", 2, vp=5.0)
    r = top_voter_share(db, "P", top_n=2)
    assert r["partial"] is True
    assert r["top_n_share_pct"] == 10.0          # 10 / 100, not 10 / 10 (= the inflated 100%)


def test_concentration_endpoint_and_chat_facts_agree(db):
    add_proposal(db, "P", votes_count=8, choices=CHOICES, scores=[16, 0, 0])
    add_votes(db, "P", 8, vp=2.0)
    assert concentration(db, "P", 4)["top_n_share_pct"] == proposal_facts(db, "P")["top_4_voters_share_pct"] == 50.0


def test_unknown_proposal(db):
    assert top_voter_share(db, "nope") is None
    assert concentration(db, "nope", 4) is None
    assert proposal_facts(db, "nope") is None
