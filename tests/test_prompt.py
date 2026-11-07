# tests/test_prompt.py
"""The relaxed prompt rules, and the evaluation scoring that depends on them."""

import eval.eval_harness as harness
import pytest

from features.chat.prompt import (ADVICE_RULES, BACKGROUND_TAG, MAX_SOURCES, SYSTEM_PROMPT, build_prompt,
                                format_facts, is_advice_question, split_evidence)

# What the agent gathered: one lookup's raw result (features/chat/agent.py gather_evidence).
FACTS = [{"tool": "proposal_details", "arguments": {"proposal_id": "0xabc"},
          "result": {"dao": "Optimism Collective", "title": "DefiLlama", "state": "closed",
                     "results": [{"choice": "For", "share_pct": 91.7}], "winning_choice": "For",
                     "total_voters": 14194, "forum_posters": 12, "silence_ratio_pct": 0.085,
                     "top_4_voters_share_pct": 50.4, "votes_loaded": 14194, "votes_partial": False}}]


def search_entry(*chunks):
    """A forum search that found these chunks, as the agent stores it."""
    return {"tool": "search_forum", "arguments": {"query": "why"}, "result": {"chunks": list(chunks)}}


def passage(cid, distance=0.3, text="I support this.", author="carol"):
    return {"id": cid, "document": text, "distance": distance,
            "metadata": {"source_type": "forum_post", "proposal_id": "P", "author": author}}


# ── the rules in the system prompt ───────────────────────────────────────────

def test_specific_facts_must_come_only_from_the_material():
    assert "use ONLY the provided material" in SYSTEM_PROMPT
    assert "Never use your own knowledge for numbers, vote results, who voted" in SYSTEM_PROMPT


def test_general_background_is_allowed_but_must_be_marked():
    assert "general background from your own knowledge" in SYSTEM_PROMPT
    assert f"start each such sentence with {BACKGROUND_TAG}" in SYSTEM_PROMPT


def test_citations_and_honesty_rules_are_kept():
    for rule in ("[Source N]", "[Facts]", "low or medium confidence", "say so plainly"):
        assert rule in SYSTEM_PROMPT


def test_the_writer_is_told_what_the_lookup_fields_mean():
    """Without these, the model invented a meaning for 'silence ratio' and a token unit for voting power."""
    assert "'Silence ratio' means forum posters divided by voters" in SYSTEM_PROMPT
    assert "Never add a token name or unit to voting power" in SYSTEM_PROMPT
    assert "never the winner" in SYSTEM_PROMPT                      # an open vote only "leads"
    assert "among the proposals in our data" in SYSTEM_PROMPT       # rankings cover the data we hold


def test_answers_are_kept_short_and_background_is_not_padding():
    """Live runs gave tables and an unrequested paragraph about what a DAO is."""
    assert "Keep it short, no tables unless asked" in SYSTEM_PROMPT
    assert "never pad an answer with it" in SYSTEM_PROMPT


def test_answers_read_like_a_person_wrote_them_without_changing_the_numbers():
    """A live A/B run found what the style rule needs: 'use separators' turned the silence ratio 11.549 into
    '11,549 %'; 'voters: 1,019' key-value lines read like a dump; the 'Want the reasons...?' offer showed up
    after a reasons answer; 'currently active' was said about votes that ended weeks ago."""
    assert "Start with the direct answer in one plain sentence" in SYSTEM_PROMPT
    assert "never 'field: value' pairs" in SYSTEM_PROMPT
    assert "never change a decimal (11.549 stays 11.549)" in SYSTEM_PROMPT       # keeps the exact-number checks valid
    assert "never shorten a number" in SYSTEM_PROMPT and "never write a number in words" in SYSTEM_PROMPT
    assert "never claim a trend unless the facts contain numbers over time" in SYSTEM_PROMPT
    assert "never 'currently', 'right now' or 'still' about a vote that is not closed" in SYSTEM_PROMPT
    assert "Only after a list of several proposals" in SYSTEM_PROMPT
    # A live answer put the 0x... ids in bold as the names and hid the titles; it also closed with "Let me know..."
    assert "Never show a proposal id (the long 0x... code) to the reader" in SYSTEM_PROMPT
    assert "Never end with 'Let me know...'" in SYSTEM_PROMPT


def test_when_nothing_is_found_the_user_hears_what_the_bot_can_do_in_plain_words():
    """The old answer was 'there is no information in the provided material': internal wording, no help."""
    assert "never say 'the material'" in SYSTEM_PROMPT
    assert "rankings of proposals" in SYSTEM_PROMPT


def test_a_greeting_gets_one_short_line_not_a_list_of_features():
    """'hi' was answered with a paragraph of capabilities; the list is only for a real question with no answer."""
    assert "Reply with a greeting ONLY when the whole message is nothing but a greeting or thanks" in SYSTEM_PROMPT
    assert "ONE short sentence" in SYSTEM_PROMPT and "without listing what you can do" in SYSTEM_PROMPT


def test_a_question_that_starts_with_hi_is_answered_not_greeted():
    """Live runs: 'hi whats the news today' fetched the newest proposals but the answer was only a greeting
    (3 of 3 tries), and 'What did Compound vote on...' opened with 'Hi! How can I help'. Wording that fixed
    both, tested on 5 messages x 2 tries: greet ONLY when nothing else is asked, otherwise start with the answer."""
    assert "(for example 'hi, what is new?'), do not greet: begin directly with the answer" in SYSTEM_PROMPT


def test_a_named_voter_comes_with_their_voting_power():
    """'Largest voter on OAT Elections' was answered with the ballot but not the 33M voting power."""
    assert "name a voter, also give their voting power" in SYSTEM_PROMPT


def test_prompt_puts_facts_before_sources_before_question():
    user = build_prompt("Why?", FACTS + [search_entry(passage("c"))])[1]["content"]
    assert user.index("DATABASE FACTS") < user.index("Sources:") < user.index("Question: Why?")
    assert "- proposal_details(proposal_id=0xabc):" in user          # what was asked ...
    assert '"winning_choice": "For"' in user                         # ... and what the database returned


def test_a_question_with_no_evidence_still_gets_a_prompt():
    user = build_prompt("What is a DAO?", [])[1]["content"]
    assert "DATABASE FACTS" not in user
    assert "(no passage was found)" in user and user.endswith("Question: What is a DAO?")


# ── turning evidence into facts and sources ──────────────────────────────────

def test_passages_are_deduplicated_closest_first_and_capped():
    first = search_entry(passage("a", 0.5), passage("b", 0.2))
    second = search_entry(passage("a", 0.5), *[passage(f"x{i}", 0.3 + i / 100) for i in range(12)])
    chunks, entries = split_evidence([first, second])
    assert [c["id"] for c in chunks][:2] == ["b", "x0"]               # nearest first
    assert len({c["id"] for c in chunks}) == len(chunks) == MAX_SOURCES   # no duplicates, capped
    assert entries == []


def test_a_search_that_found_nothing_is_reported_as_a_fact():
    empty = {"tool": "search_forum", "arguments": {"query": "x", "author": "nobody"},
             "result": {"error": "No forum posts by 'nobody' in our data."}}
    chunks, entries = split_evidence([empty] + FACTS)
    assert chunks == [] and [e["tool"] for e in entries] == ["search_forum", "proposal_details"]
    assert "No forum posts by 'nobody'" in format_facts(entries)       # the writer can say so


def test_format_facts_is_empty_without_entries():
    assert format_facts([]) == ""


# ── evaluation scoring ───────────────────────────────────────────────────────

def test_background_share_counts_marked_sentences():
    answer = "[Background] A DAO is run by token holders. The proposal passed with 91.7% [Facts]."
    assert harness.background_share(answer) == 0.5
    assert harness.background_share("It passed [Facts].") == 0.0


def test_faithfulness_judge_sees_the_facts_and_ignores_background(monkeypatch):
    sent = {}

    def fake_judge_llm(messages):
        sent["prompt"] = messages[0]["content"]
        return "SCORE: 1.0 | REASON: supported", "fake"

    monkeypatch.setattr(harness, "generate", fake_judge_llm)
    score, _ = harness.score_faithfulness("It passed with 91.7% [Facts].", ["some source text"], FACTS)

    assert score == 1.0
    assert '"share_pct": 91.7' in sent["prompt"]              # the lookup results are part of the material
    assert f"IGNORE every sentence that starts with {BACKGROUND_TAG}" in sent["prompt"]


# ── advice mode ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("question", [
    'Should I vote for "Approve Release of Frozen ETH"?', "How should I vote on this proposal?",
    "Where should I vote for this proposal", "What should I vote on the DefiLlama grant?",
    "Which way should I vote?", "How would you vote on this?", "Can you recommend how to vote on this one?",
    "Any advice on how to vote?", "Is it worth voting for this?", "Should we vote yes?",
])
def test_advice_questions_are_recognised(question):
    assert is_advice_question(question)


@pytest.mark.parametrize("question", [
    "How did entropy vote on X, and with how much voting power?", "Who voted against the proposal?",
    "Why did people vote for it?", "What was the result of the vote?", "How many wallets voted on it?",
    "What is a delegate in DAO governance?", "Did the largest voter vote for or against?",
    "How does voting work in the Token House?", "",
])
def test_questions_about_votes_are_not_advice_questions(question):
    assert not is_advice_question(question)


def test_advice_question_gets_the_no_recommendation_rules():
    system = build_prompt("Should I vote for this?", FACTS)[0]["content"]
    assert system == SYSTEM_PROMPT + ADVICE_RULES
    assert "must NOT tell the user how to vote" in system
    assert "arguments in favour" in system and "arguments against" in system
    assert "the decision is yours" in system
    assert "ask which one" in system                       # no proposal known -> ask, do not guess
    assert "Never add an argument the sources do not contain" in system      # no invented 'typical' concerns
    assert "The sources contain no arguments" in system                       # an empty side is stated, not filled in


def test_every_other_question_gets_exactly_the_normal_prompt():
    for question in ("Why did people support it?", "How did entropy vote?", "What is a delegate?"):
        assert build_prompt(question, FACTS)[0]["content"] == SYSTEM_PROMPT


def test_advice_mode_keeps_the_grounding_rules_and_the_user_message():
    normal, advice = build_prompt("Why?", FACTS), build_prompt("Should I vote for it?", FACTS)
    assert advice[0]["content"].startswith(SYSTEM_PROMPT)               # citations, [Background] rules still apply
    assert advice[1]["content"].split("Question:")[0] == normal[1]["content"].split("Question:")[0]


# ── source safety cap ─────────────────────────────────────────────────────────

def test_an_oversized_source_is_cut_at_a_word_and_marked():
    from features.chat.prompt import MAX_SOURCE_CHARS, SHORTENED_MARK, clip_source
    long_text = "word " * 2000
    clipped = clip_source(long_text)
    assert len(clipped) <= MAX_SOURCE_CHARS + len(SHORTENED_MARK)
    assert clipped.endswith(SHORTENED_MARK) and "wor " not in clipped.replace("word ", "")      # no half word
    assert clip_source("short source") == "short source"


def test_the_prompt_stays_small_even_with_a_huge_source():
    huge = {"id": "c", "document": "x " * 30000, "distance": 0.3, "metadata": {"source_type": "forum_post"}}
    hugest = [search_entry(dict(huge, id=f"c{i}")) for i in range(5)]
    user = build_prompt("Why?", hugest + FACTS)[1]["content"]
    assert len(user) < 5 * 2200 + 1500                           # 5 capped sources + facts + question
