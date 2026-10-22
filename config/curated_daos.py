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
    Append {"id": "<snapshot space id>", "name": "<display name>"}, then run
    python -m features.sync.runner --sync-all: the next sync stores its space row
    and its latest 20 proposals, then their forum threads and votes.
"""

CURATED_DAOS = [
    {"id": "arbitrumfoundation.eth", "name": "Arbitrum DAO"},
    {"id": "aavedao.eth", "name": "Aave DAO"},
    {"id": "opcollective.eth", "name": "Optimism Collective"},
    {"id": "uniswapgovernance.eth", "name": "Uniswap"},
    {"id": "ens.eth", "name": "ENS"},
]


# ── Where control goes next ───────────────────────────────────────────────────
# Read by features/proposals/fetch.py (what to sync) and features/daos/routes.py
# (what GET /daos lists).
