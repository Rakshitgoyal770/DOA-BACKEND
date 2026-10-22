# tests/test_prompt.py
"""The relaxed prompt rules, and the evaluation scoring that depends on them."""

import eval.eval_harness as harness
from features.chat.prompt import BACKGROUND_TAG, SYSTEM_PROMPT, build_prompt

FACTS = [{"dao": "Optimism Collective", "title": "DefiLlama", "state": "closed",
          "results": [{"choice": "For", "share_pct": 91.7}], "winning_choice": "For",
          "total_voters": 14194, "forum_posters": 12, "silence_ratio_pct": 0.085,
          "top_4_voters_share_pct": 50.4, "votes_loaded": 14194, "votes_partial": False}]


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


def test_prompt_puts_facts_before_sources_before_question():
    chunk = {"id": "c", "document": "I support this.", "metadata": {"source_type": "proposal_body"}}
    user = build_prompt("Why?", [chunk], FACTS)[1]["content"]
    assert user.index("PROPOSAL FACTS") < user.index("Sources:") < user.index("Question: Why?")


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
    assert "For 91.7%" in sent["prompt"]                      # facts are part of the material
    assert f"IGNORE every sentence that starts with {BACKGROUND_TAG}" in sent["prompt"]
