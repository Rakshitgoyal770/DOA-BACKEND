# config/curated_daos.py
"""
config/curated_daos.py — The DAOs this project follows.

WHAT THIS FILE DOES
    CURATED_DAOS lists the Snapshot spaces we collect. Everything else follows
    from it: the proposal sync (features/proposals/fetch.py) fetches these DAOs,
    and GET /daos (features/daos/routes.py) reports on them.

WHY A HAND-PICKED LIST
    Snapshot's public API has no reliable way to discover "major" DAOs (spaces
    can only be filtered by id/verified/turbo/domain/search/created, none of
    which surface them), so each id here was checked with a direct
    space(id: "...") lookup.

TO ADD A DAO
    Append {"id": "<snapshot space id>", "name": "<display name>", "aliases": [...]}, then run
    python -m features.sync.runner --sync-all: the next sync stores its space row
    and its latest 20 proposals, then their forum threads and votes.
"""

# "aliases" are the words people use for the DAO in a question; the chat looks for
# them (whole words, any case) to add that DAO's facts (features/chat/context.py).
CURATED_DAOS = [
    {"id": "arbitrumfoundation.eth", "name": "Arbitrum DAO", "aliases": ["arbitrum"]},
    {"id": "aavedao.eth", "name": "Aave DAO", "aliases": ["aave"]},
    {"id": "opcollective.eth", "name": "Optimism Collective", "aliases": ["optimism", "op collective"]},
    {"id": "uniswapgovernance.eth", "name": "Uniswap", "aliases": ["uniswap"]},
    {"id": "ens.eth", "name": "ENS", "aliases": ["ens"]},
]


# ── Where control goes next ───────────────────────────────────────────────────
# Read by features/proposals/fetch.py (what to sync), features/daos/routes.py
# (what GET /daos lists) and features/chat/context.py (DAO names in questions).
