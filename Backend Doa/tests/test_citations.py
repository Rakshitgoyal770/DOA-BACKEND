# tests/test_citations.py
"""features/chat/citations.py (the check) and service.check_and_repair (what happens when an answer fails it)."""

import features.chat.service as service
from features.chat.citations import (check_citations, cited_sources, cites_facts, correction_request,
                                     strip_invalid, unsupported_numbers)


def test_cited_sources_reads_every_way_the_writer_cites():
    answer = "A [Source 2]. B [Source 1, 3]. C [Source 1, Source 4] [Facts] [Background] and [x]."
    assert cited_sources(answer) == [2, 1, 3, 4]
    assert cited_sources("no citations") == [] and cited_sources(None) == []
    assert cites_facts(answer) and not cites_facts("[Source 1]")


def test_a_citation_of_a_source_that_was_not_given_is_invalid():
    check = check_citations("Yes [Source 1]. Also [Source 9] and [Source 0].", source_count=4, has_facts=True)
    assert check["invalid_sources"] == [9, 0] and check["ok"] is False
    assert check_citations("Yes [Source 1][Source 4].", 4, True)["ok"] is True
    assert check_citations("Yes [Source 1].", 0, False)["invalid_sources"] == [1]


def test_facts_cannot_be_cited_when_there_were_none():
    check = check_citations("It passed [Facts].", source_count=2, has_facts=False)
    assert check["facts_without_facts"] and not check["ok"]
    assert check_citations("It passed [Facts].", 2, True)["ok"]


def test_a_number_that_is_nowhere_in_the_evidence_is_reported_but_does_not_fail_the_answer():
    evidence = 'DATABASE FACTS: {"total_voters": 63845, "share": 93.8, "choices": 3}\nQuestion: how many?'
    assert unsupported_numbers("63,845 voters, 93.8% For, 3 options.", evidence) == []
    assert unsupported_numbers("About 64,000 voters, 94.2% For.", evidence) == ["64,000", "94.2"]
    assert unsupported_numbers("93.80 and 63845", evidence) == []                  # 93.80 is 93.8
    check = check_citations("About 64,000 voters [Facts].", 0, True, evidence)
    assert check["ok"] and check["unsupported_numbers"] == ["64,000"]
    assert check_citations("About 64,000 voters.", 0, True)["unsupported_numbers"] == []     # no evidence text: not checked


def test_markers_that_point_at_nothing_are_removed_and_the_rest_is_kept():
    answer = "Yes [Source 1] and also [Source 1, Source 9]. More [Source 9]. Done [Facts]."
    assert strip_invalid(answer, 2, True) == "Yes [Source 1] and also [Source 1]. More. Done [Facts]."
    assert strip_invalid("Done [Facts].", 2, False) == "Done."
    assert strip_invalid("Fine [Source 2] [Background].", 2, True) == "Fine [Source 2] [Background]."


def test_the_correction_names_the_problem():
    check = check_citations("A [Source 9]. B [Facts].", 3, False)
    message = correction_request(check, 3)
    assert "[Source 9]" in message and "only Sources 1-3 exist" in message and "no database facts" in message
    assert "no sources were given" in correction_request({"invalid_sources": [1], "facts_without_facts": False}, 0)


# ── what run_chat does about it ───────────────────────────────────────────────

def evidence_with_two_passages():
    chunks = [{"id": f"c{i}", "document": f"Passage number {i}.", "distance": 0.3,
               "metadata": {"source_type": "forum_post", "proposal_id": "P", "author": "carol"}, "sql": {}}
              for i in (1, 2)]
    return [{"tool": "search_forum", "arguments": {"query": "q"}, "result": {"chunks": chunks}}]


def test_a_good_answer_passes_through_untouched(monkeypatch):
    monkeypatch.setattr(service, "generate", lambda messages: (_ for _ in ()).throw(AssertionError("no rewrite needed")))
    answer, provider, check = service.check_and_repair("why?", evidence_with_two_passages(), "Yes [Source 2].", "groq")
    assert (answer, provider, check["ok"], "repaired" in check) == ("Yes [Source 2].", "groq", True, False)


def test_a_bad_citation_makes_the_writer_rewrite_once_with_the_problem_named(monkeypatch):
    seen = []

    def generate(messages):
        seen.append(messages)
        return "Yes [Source 1].", "gemini"
    monkeypatch.setattr(service, "generate", generate)
    answer, provider, check = service.check_and_repair("why?", evidence_with_two_passages(), "Yes [Source 7].", "groq")
    assert (answer, provider, check["repaired"], check["ok"]) == ("Yes [Source 1].", "gemini", "rewritten", True)
    assert len(seen) == 1 and [m["role"] for m in seen[0]] == ["system", "user", "assistant", "user"]
    assert seen[0][2]["content"] == "Yes [Source 7]." and "[Source 7]" in seen[0][3]["content"]


def test_a_rewrite_that_is_still_wrong_is_stripped(monkeypatch):
    monkeypatch.setattr(service, "generate", lambda messages: ("Again [Source 5].", "gemini"))
    answer, provider, check = service.check_and_repair("why?", evidence_with_two_passages(), "Yes [Source 7].", "groq")
    assert answer == "Again." and provider == "gemini" and check["repaired"] == "stripped" and check["ok"]


def test_when_no_provider_can_rewrite_the_bad_markers_are_stripped(monkeypatch):
    def down(messages):
        raise RuntimeError("All providers failed. Last error: quota")
    monkeypatch.setattr(service, "generate", down)
    answer, provider, check = service.check_and_repair("why?", evidence_with_two_passages(), "Yes [Source 7] and [Source 2].", "groq")
    assert answer == "Yes and [Source 2]." and provider == "groq" and check["repaired"] == "stripped" and check["ok"]
