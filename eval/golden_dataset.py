"""
Golden Dataset for DAO Governance Intelligence Evaluation
==========================================================
Contains benchmark questions, proposal scoping IDs, and ground truth chunk IDs
extracted from real Snapshot proposals and Discourse forum posts.
"""

GOLDEN_DATASET = [
    {
        "id": "case_1_arbitrum_watchdog",
        "question": "Why did delegates vote to ban Good Entry in the Watchdog Program?",
        "proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
        "ground_truth_context_ids": [
            "proposal_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_0",
            "forum_post_78189",
            "forum_post_78202"
        ],
        "expected_topics": ["Watchdog Program", "misuse of funds", "lack of response"]
    },
    {
        "id": "case_2_optimism_grants_council",
        "question": "How many Reviewers will the Token House elect to the Growth Experiments sub-committee?",
        "proposal_id": "0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453",
        "ground_truth_context_ids": [
            "proposal_0xa9457a5344747a6c272de786419fc7a4e83fcf0f927ef9b1ce767452faa9b453_0"
        ],
        "expected_topics": ["5 Reviewers", "Growth Experiments", "Grants Council"]
    },
    {
        "id": "case_3_optimism_velodrome",
        "question": "Who are the authors and contact persons listed for the Velodrome Finance proposal?",
        "proposal_id": "0xfeb1832a75e2ef47dea4b08509a16e4e9176e9d2a962c9466c5d345b37428384",
        "ground_truth_context_ids": [
            "forum_post_15198"
        ],
        "expected_topics": ["Alex", "Jack", "Tao", "Velodrome"]
    },
    {
        "id": "case_4_optimism_ambire",
        "question": "Who posted the Optimistic Ambire OP Incentive Proposal in the forum?",
        "proposal_id": "0x71f465ebc109ddbda430a6a0312a43c324d0653624eb22e126e7503681dceb10",
        "ground_truth_context_ids": [
            "forum_post_15539"
        ],
        "expected_topics": ["vanzoo", "Ambire Wallet", "OP Incentive"]
    },
    {
        "id": "case_5_optimism_defillama",
        "question": "Who submitted the Season 2 Cycle 8 proposal for DefiLlama?",
        "proposal_id": "0xe97adad42eb8c0072edee33de2c68191cd2e8a0ae615ab94ebb60bdc73a7d3f2",
        "ground_truth_context_ids": [
            "forum_post_13823"
        ],
        "expected_topics": ["0xngmi", "DefiLlama"]
    }
]