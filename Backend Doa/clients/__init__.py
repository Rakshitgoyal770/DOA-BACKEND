# clients/__init__.py
"""
clients/__init__.py — The clients package: the only code that talks to outside services.

    clients/snapshot.py   Snapshot GraphQL API   proposals, votes, DAO (space) info
    clients/discourse.py  Discourse forums       threads, posts, user profiles
    clients/ens.py        ENS lookup API         wallet <-> ENS name

These modules only fetch and translate; they never touch the database. The
features/ modules decide WHAT to fetch and store the results.
"""

# Sent with every forum and ENS request, so the services can identify us.
USER_AGENT = "Mozilla/5.0 (compatible; DAOGovernanceResearch/0.1)"
