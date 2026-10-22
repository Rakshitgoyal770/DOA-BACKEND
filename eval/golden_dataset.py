# eval/golden_dataset.py
"""
eval/golden_dataset.py — Benchmark questions with the sources a correct answer must use.

WHAT THIS FILE DOES
    Each case is a real question about a real proposal, with:
      proposal_id               the search is limited to this proposal (like the chat's proposal_id)
      ground_truth_context_ids  the index documents that contain the answer
      expected_topics           what a good answer should mention (for a human reading results)
    eval/eval_harness.py checks whether those documents were retrieved
    (context recall / precision) and lets an LLM judge the answer.

DOCUMENT ID FORMAT (must match vector/embedding.py)
    proposal_<proposal_id>_<chunk number>
    forum_post_<proposal_id>_<Discourse post id>
    The forum ids used to be forum_post_<post id>; they changed when a post became
    stored once per proposal. Old ids silently score as "not retrieved".

TO ADD A CASE
    Pick a proposal, ask a question, find the answering document ids with a
    search (or GET /chat's "sources"), and append a dict like the ones below.
"""

GOLDEN_DATASET = [
    {
        "id": "case_1_arbitrum_watchdog",
        "question": "Why did delegates vote to ban Good Entry in the Watchdog Program?",
        "proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
        "ground_truth_context_ids": [
            "proposal_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_0",
            "forum_post_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_78189",
            "forum_post_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_78202",
        ],
        "expected_topics": ["Watchdog Program", "misuse of funds", "lack of response"],
    },
    {
        "id": "case_2_optimism_grants_council",
        "question": "How many Reviewers will the Token House elect to the Growth Experiments sub-committee?",
        "proposal_id": "0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453",
        "ground_truth_context_ids": [
            "proposal_0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453_0",
        ],
        "expected_topics": ["5 Reviewers", "Growth Experiments", "Grants Council"],
    },
    {
        "id": "case_3_optimism_velodrome",
        "question": "Who are the authors and contact persons listed for the Velodrome Finance proposal?",
        "proposal_id": "0xfeb1832a75e2ef47dea4b08509a16e4e9176e9d2a962c9466c5d345b37428384",
        "ground_truth_context_ids": [
            "forum_post_0xfeb1832a75e2ef47dea4b08509a16e4e9176e9d2a962c9466c5d345b37428384_15198",
        ],
        "expected_topics": ["Alex", "Jack", "Tao", "Velodrome"],
    },
    {
        "id": "case_4_optimism_ambire",
        "question": "Who posted the Optimistic Ambire OP Incentive Proposal in the forum?",
        "proposal_id": "0x71f465ebc109ddbda430a6a0312a43c324d0653624eb22e126e7503681dceb10",
        "ground_truth_context_ids": [
            "forum_post_0x71f465ebc109ddbda430a6a0312a43c324d0653624eb22e126e7503681dceb10_15539",
        ],
        "expected_topics": ["vanzoo", "Ambire Wallet", "OP Incentive"],
    },
    {
        "id": "case_5_optimism_defillama",
        "question": "Who submitted the Season 2 Cycle 8 proposal for DefiLlama?",
        "proposal_id": "0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2",
        "ground_truth_context_ids": [
            "forum_post_0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2_13823",
        ],
        "expected_topics": ["0xngmi", "DefiLlama"],
    },
]


# ── Where control goes next ───────────────────────────────────────────────────
# Read by eval/eval_harness.py run_eval(). tests/test_regression_real_db.py checks
# that every ground_truth_context_id exists in the index, so an id-format change
# cannot silently break the evaluation again.
