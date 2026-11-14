# tests/test_retrieval_eval.py
"""eval/retrieval_eval.py: the scoring of a search result (no model, no index)."""

from eval.retrieval_eval import evaluate, load_cases, score_case, summarise

CASE = {"id": "c1", "question": "q", "expected_chunk": "forum_post_P_1", "expected_hash": "h1",
        "proposal_id": "P", "space_id": "S", "source_type": "forum_post"}


def chunk(cid, content_hash, distance, proposal_id="P"):
    return {"id": cid, "distance": distance, "metadata": {"content_hash": content_hash, "proposal_id": proposal_id}}


def test_the_passage_is_found_by_hash_so_a_copy_under_another_proposal_counts():
    found = score_case(CASE, [chunk("x", "h0", 0.2, "Q"), chunk("forum_post_Q_1", "h1", 0.9, "Q")], cutoff=0.7)
    assert (found["rank"], found["distance"], found["within_cutoff"]) == (2, 0.9, False)
    assert found["right_proposal_at_5"] == 0.0 and found["top1_distance"] == 0.2
    assert score_case(CASE, [chunk("x", "h0", 0.2)], cutoff=0.7)["rank"] is None
    assert score_case(CASE, [], cutoff=0.7) == {"rank": None, "distance": None, "within_cutoff": False,
                                               "right_proposal_at_5": 0.0, "top1_distance": None}


def test_the_summary_counts_ranks_and_the_cutoff():
    rows = [{"rank": 1, "within_cutoff": True, "right_proposal_at_5": 1.0},
            {"rank": 7, "within_cutoff": True, "right_proposal_at_5": 0.5},
            {"rank": 3, "within_cutoff": False, "right_proposal_at_5": 0.5},
            {"rank": None, "within_cutoff": False, "right_proposal_at_5": 0.0}]
    out = summarise(rows)
    assert (out["found@5"], out["found@8"], out["delivered@5"], out["not_in_top_30"]) == (50.0, 75.0, 25.0, 1)
    assert out["mrr@8"] == round((1 + 1 / 7 + 1 / 3) / 4, 3) and out["right_proposal@5"] == 50.0


def test_every_case_is_searched_anywhere_in_its_dao_and_in_its_proposal():
    seen = []

    def search(question, where, n):
        seen.append(where)
        return [chunk("forum_post_P_1", "h1", 0.3)] if where else []      # only the filtered searches find it
    report = evaluate([CASE], search)
    assert seen == [None, {"space_id": "S"}, {"proposal_id": "P"}]
    assert report["summary"]["anywhere"]["found@5"] == 0.0 and report["summary"]["proposal"]["found@5"] == 100.0
    assert report["by_source_type"]["forum_post"]["dao"]["cases"] == 1


def test_the_saved_question_set_is_well_formed():
    cases = load_cases()
    assert len(cases) >= 40 and len({c["id"] for c in cases}) == len(cases)
    assert all(c["question"] and c["expected_hash"] and c["proposal_id"] and c["space_id"] for c in cases)
