# eval/golden_dataset.py
"""
eval/golden_dataset.py — The golden dataset: hand-written cases + generated cases.

WHAT THIS FILE DOES
    GOLDEN_DATASET is every test question the evaluation runs:
      * CURATED     5 hand-written questions (below) whose answers are in a specific
                    proposal text or forum post
      * generated   built from the database by eval/build_golden.py and stored in
                    eval/golden_generated.json (every level and question type)

CASE FORMAT
    {"id", "level", "intent", "question",
     "scope":    {"proposal_id": ...} | {"dao_id": ...} | {},
     "expected": {"numbers":  [{"label", "value", "kind": pct|count|vp}],
                  "mentions": [names, or "title:<proposal title>"],
                  "sources":  [index document ids; at least one must be retrieved],
                  "behavior": answer | no_recommendation | say_insufficient |
                              ask_clarify | background_tagged},
     "volatile": true if the expected answer changes as new data arrives,
     "needs":    the feature the case depends on, if not built yet}
    How each field is checked: eval/checks.py.

DOCUMENT ID FORMAT (must match vector/embedding.py)
    proposal_<proposal_id>_<chunk number>
    forum_post_<proposal_id>_<Discourse post id>

TO ADD A CASE
    Generated types: add a template in eval/build_golden.py and re-run it.
    A one-off question: append it to CURATED below in the format above.
"""

import json
from pathlib import Path

GENERATED_PATH = Path(__file__).with_name("golden_generated.json")

CURATED = [
    {
        "id": "cur_arbitrum_watchdog", "level": "detail", "intent": "explain",
        "question": "Why did delegates vote to ban Good Entry in the Watchdog Program?",
        "scope": {"proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c"},
        "expected": {"numbers": [], "mentions": [], "behavior": "answer", "sources": [
            "proposal_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_0",
            "forum_post_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_78189",
            "forum_post_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_78202"]},
        "volatile": False, "needs": None, "note": "topics: Watchdog Program, misuse of funds, lack of response",
    },
    {
        "id": "cur_optimism_grants_council", "level": "detail", "intent": "explain",
        "question": "How many Reviewers will the Token House elect to the Growth Experiments sub-committee?",
        "scope": {"proposal_id": "0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453"},
        "expected": {"numbers": [{"label": "reviewers", "value": 5, "kind": "count"}],
                     "mentions": ["Growth Experiments"], "behavior": "answer", "sources": [
            "proposal_0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453_0"]},
        "volatile": False, "needs": None, "note": None,
    },
    {
        "id": "cur_optimism_velodrome", "level": "detail", "intent": "who_said",
        "question": "Who are the authors and contact persons listed for the Velodrome Finance proposal?",
        "scope": {"proposal_id": "0xfeb1832a75e2ef47dea4b08509a16e4e9176e9d2a962c9466c5d345b37428384"},
        "expected": {"numbers": [], "mentions": ["Alex", "Jack", "Tao"], "behavior": "answer", "sources": [
            "forum_post_0xfeb1832a75e2ef47dea4b08509a16e4e9176e9d2a962c9466c5d345b37428384_15198"]},
        "volatile": False, "needs": None, "note": None,
    },
    {
        "id": "cur_optimism_ambire", "level": "detail", "intent": "who_said",
        "question": "Who posted the Optimistic Ambire OP Incentive Proposal in the forum?",
        "scope": {"proposal_id": "0x71f465ebc109ddbda430a6a0312a43c324d0653624eb22e126e7503681dceb10"},
        "expected": {"numbers": [], "mentions": ["vanzoo"], "behavior": "answer", "sources": [
            "forum_post_0x71f465ebc109ddbda430a6a0312a43c324d0653624eb22e126e7503681dceb10_15539"]},
        "volatile": False, "needs": None, "note": None,
    },
    {
        "id": "cur_optimism_defillama", "level": "detail", "intent": "who_said",
        "question": "Who submitted the Season 2 Cycle 8 proposal for DefiLlama?",
        "scope": {"proposal_id": "0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2"},
        "expected": {"numbers": [], "mentions": ["0xngmi"], "behavior": "answer", "sources": [
            "forum_post_0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2_13823"]},
        "volatile": False, "needs": None, "note": None,
    },
]


def load_generated() -> list[dict]:
    """The cases written by eval/build_golden.py ([] if it has not been run yet)."""
    if not GENERATED_PATH.exists():
        return []
    return json.loads(GENERATED_PATH.read_text(encoding="utf-8"))["cases"]


GOLDEN_DATASET = CURATED + load_generated()


# ── Where control goes next ───────────────────────────────────────────────────
# Read by eval/eval_harness.py run_eval(). tests/test_golden.py checks that every
# case is well-formed, that its expected numbers match the database, and that every
# expected source id exists in the search index.
