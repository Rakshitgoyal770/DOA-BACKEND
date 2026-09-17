# config/curated_daos.py
"""
Curated DAO shortlist.

Snapshot's public API has no reliable way to auto-discover "top" DAOs by
activity or significance (confirmed via GraphQL introspection — spaces
can only be exact-filtered by id/verified/turbo/domain/search/created,
none of which reliably surface major DAOs). So this list is hand-verified
via direct space(id: "...") lookups instead of automated discovery.
"""

CURATED_DAOS = [
    {"id": "arbitrumfoundation.eth", "name": "Arbitrum DAO"},
    {"id": "aavedao.eth", "name": "Aave DAO"},
    {"id": "opcollective.eth", "name": "Optimism Collective"},
    {"id": "uniswapgovernance.eth", "name": "Uniswap"},
    {"id": "ens.eth", "name": "ENS"},
]

SPACE_IDS = [dao["id"] for dao in CURATED_DAOS]