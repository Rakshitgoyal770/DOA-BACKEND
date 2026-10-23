# tests/test_golden.py
"""The golden dataset (well-formed, correct against the data) and the exact checks that grade it."""

import pytest

import db.schema as schema
import eval.checks as checks
from eval.golden_dataset import GOLDEN_DATASET

LEVELS = {"dashboard", "dao", "proposal", "detail", "behaviour"}
BEHAVIORS = {"answer", "no_recommendation", "say_insufficient", "ask_clarify", "background_tagged"}


# ── the exact checks ──────────────────────────────────────────────────────────

def test_numbers_are_read_the_way_people_write_them():
    assert checks.numbers_in("For 91.7%, 14,194 voters, 33.0M power, 1.5K posts") == [91.7, 14194, 33e6, 1500]
    assert checks.numbers_in("wallet 0xab12cd") == [0]           # digits inside hex are not numbers


def test_number_tolerances():
    pct, count, vp = ({"label": "x", "value": 91.7, "kind": "pct"}, {"label": "n", "value": 14194, "kind": "count"},
                      {"label": "vp", "value": 33030451.22, "kind": "vp"})
    assert checks.check_numbers("It got 91.66%", [pct]) == []
    assert checks.check_numbers("It got 92.1%", [pct]) == ["x=91.7"]
    assert checks.check_numbers("14,194 wallets", [count]) == []
    assert checks.check_numbers("14,195 wallets", [count]) == ["n=14194"]
    assert checks.check_numbers("about 33.0M", [vp]) == []           # within 1%


def test_mentions_and_long_titles():
    title = "title:[Constitutional] AIP: Ratification of Security Council Election Process Improvements"
    assert checks.check_mentions("The Security Council Election Process ratification passed.", [title]) == []
    assert checks.check_mentions("Something else entirely.", [title]) == [title]
    assert checks.check_mentions("Entropy voted For.", ["entropy", "For"]) == []


def test_sources_need_at_least_one_hit():
    assert checks.check_sources(["a", "b"], ["b", "c"]) == (True, 0.5)
    assert checks.check_sources(["a"], ["c"]) == (False, 0.0)
    assert checks.check_sources([], []) == (True, 1.0)


def test_behaviour_checks_without_and_with_the_judge(monkeypatch):
    assert checks.check_behavior("q", None, "answer")[0] is False
    assert checks.check_behavior("q", None, "say_insufficient")[0] is True       # a refusal is not a made-up answer
    assert checks.check_behavior("q", "[Background] A DAO is ...", "background_tagged")[0] is True
    assert checks.check_behavior("q", "A DAO is ...", "background_tagged")[0] is False
    monkeypatch.setattr(checks, "generate", lambda m: ("NO - it says vote For", "fake"))
    assert checks.check_behavior("Should I vote?", "Vote For.", "no_recommendation")[0] is False


def test_grade_combines_every_check():
    case = {"question": "q", "expected": {"numbers": [{"label": "n", "value": 5, "kind": "count"}],
                                          "mentions": ["Alice"], "sources": ["doc1"], "behavior": "answer"}}
    assert checks.grade(case, "Alice counted 5.", ["doc1"])["passed"] is True
    failed = checks.grade(case, "Bob counted 6.", ["doc2"])
    assert failed["passed"] is False and len(failed["failures"]) == 3


# ── the dataset is well-formed and covers every type ─────────────────────────

def test_every_case_is_well_formed():
    ids = [c["id"] for c in GOLDEN_DATASET]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in GOLDEN_DATASET:
        assert c["level"] in LEVELS, c["id"]
        assert c["expected"]["behavior"] in BEHAVIORS, c["id"]
        assert c["question"].strip(), c["id"]
        for n in c["expected"]["numbers"]:
            assert n["kind"] in {"pct", "count", "vp"}, c["id"]


def test_dataset_covers_broad_to_narrow_and_every_behaviour():
    assert {c["level"] for c in GOLDEN_DATASET} == LEVELS
    assert {c["expected"]["behavior"] for c in GOLDEN_DATASET} == BEHAVIORS
    assert len({(c["level"], c["intent"]) for c in GOLDEN_DATASET}) >= 20


# ── the expected answers are correct (real database) ─────────────────────────

real_db = pytest.mark.skipif(not schema.DB_PATH.exists(), reason="real database not present")


@real_db
def test_stable_expected_numbers_agree_with_the_apps_own_formulas():
    """build_golden computes expected values with raw SQL; metrics.py is the app's
    implementation. Two independent calculations must give the same answer."""
    from features.chat.context import proposal_facts
    conn = schema.get_connection()
    try:
        checked = 0
        for c in GOLDEN_DATASET:
            pid = c["scope"].get("proposal_id")
            if c["volatile"] or not pid or c["level"] != "proposal":
                continue
            facts = proposal_facts(conn, pid)
            for n in c["expected"]["numbers"]:
                app_value = {"winner %": max(r["share_pct"] for r in facts["results"]),
                             "voters": facts["total_voters"], "top-4 %": facts["top_4_voters_share_pct"],
                             "forum posters": facts["forum_posters"]}[n["label"]]
                assert abs(app_value - n["value"]) <= 0.05, (c["id"], n, app_value)
                checked += 1
        assert checked >= 8
    finally:
        conn.close()


@real_db
def test_every_expected_source_exists_in_the_search_index():
    from vector.embedding import get_collection
    ids = sorted({i for c in GOLDEN_DATASET for i in c["expected"]["sources"]})
    assert sorted(get_collection().get(ids=ids)["ids"]) == ids


@real_db
def test_expected_titles_are_real_proposals():
    conn = schema.get_connection()
    try:
        titles = {r[0] for r in conn.execute("SELECT title FROM proposals")}
    finally:
        conn.close()
    for c in GOLDEN_DATASET:
        for m in c["expected"]["mentions"]:
            if m.startswith("title:"):
                assert m[6:] in titles, (c["id"], m)


# ── regressions found by reading the first real evaluation run ───────────────

def test_scale_words_are_understood_like_suffixes():
    """The model wrote '33.0 million'; the checker only knew '33.0M' and failed a correct answer."""
    assert checks.numbers_in("33.0 million votes, 2 billion, 5 thousand") == [33e6, 2e9, 5e3]
    vp = {"label": "vp", "value": 33030451.22, "kind": "vp"}
    assert checks.check_numbers("using 33.0 million voting power", [vp]) == []


def test_typographic_spaces_and_dashes_do_not_break_name_matching():
    """Models often type 'A.J.\u202fWarner' (narrow no-break space) or a long dash; it looks identical."""
    assert checks.check_mentions("A.J.\u202fWarner \u2013 18.5% (winner)", ["A.J. Warner"]) == []
    assert checks.check_mentions("Mastermojo\u00a0(Synthetix Ambassador)", ["Mastermojo (Synthetix"]) == []


def test_closest_vote_cases_only_use_two_or_three_option_proposals():
    """A 9-candidate election won on 18.5% is not a 'close vote'; it made the first expected values wrong."""
    for c in GOLDEN_DATASET:
        if c["intent"] == "closest":
            assert c["expected"]["numbers"][0]["value"] > 33, c["id"]    # with <= 3 options the winner holds > 1/3


def test_provider_errors_are_reported_apart_from_failures(capsys):
    import eval.eval_harness as harness
    cases = [{"id": "a", "level": "proposal", "intent": "result", "needs": None},
             {"id": "b", "level": "proposal", "intent": "result", "needs": None}]
    results = [{"id": "a", "passed": True, "failures": []},
               {"id": "b", "passed": False, "error": True, "failures": ["error: All providers failed"]}]
    harness.print_report(cases, results)
    out = capsys.readouterr().out
    assert "PASSED" in out and " 1/1 answered cases" in out           # the error is not in the pass rate
    assert "[error, not scored] b" in out


def test_regrade_rescored_saved_answers_without_calling_the_llm(tmp_path, monkeypatch):
    import json
    import eval.eval_harness as harness
    case = {"id": "x", "level": "proposal", "intent": "result", "needs": None, "question": "Q?",
            "scope": {}, "expected": {"numbers": [{"label": "n", "value": 5, "kind": "count"}],
                                      "mentions": [], "sources": [], "behavior": "answer"}}
    monkeypatch.setattr(harness, "GOLDEN_DATASET", [case])
    monkeypatch.setattr(harness, "run_chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("answered again")))
    saved = tmp_path / "run.json"
    saved.write_text(json.dumps({"results": [
        {"id": "x", "question": "Q?", "passed": False, "failures": ["old"], "answer": "It was 5.", "retrieved": []},
        {"id": "x", "question": "an older, different question", "passed": False, "failures": [], "answer": "y"},
    ]}), encoding="utf-8")

    results = harness.regrade(str(saved))

    assert len(results) == 1 and results[0]["passed"] is True          # re-scored with the current checks
