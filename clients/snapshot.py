# clients/snapshot.py
"""
clients/snapshot.py — Reads proposals, votes and DAO info from Snapshot's GraphQL API.

WHAT THIS FILE DOES
    Snapshot (https://hub.snapshot.org/graphql) is where these DAOs hold their
    votes. This file sends GraphQL queries and returns plain Python dicts:
      * get_space                     one DAO's info (name, counts)
      * get_proposals                 the newest N proposals of a DAO
      * get_proposals_by_ids          specific proposals, by id
      * iter_proposals_created_after  every proposal published after a time
      * iter_all_votes                every vote of a proposal

HOW PAGING WORKS (the important part)
    Snapshot returns at most 1,000 items per request and refuses `skip` above
    5,000, so "page 1, page 2, ..." stops at about 6,000 items. Instead we page
    by TIME: ask for items created at or after the newest timestamp seen so far.
        page 1: created_gte = start      -> 1,000 items, the last one at T1
        page 2: created_gte = T1         -> next items (those AT T1 come back again
                                            and are skipped, so none is lost)
        ... until a page has fewer than 1,000 items.
    `_iter_by_created` implements this once; votes and proposals both use it.

WHERE IT SITS
    features/proposals/fetch.py, features/votes/fetch.py --> THIS FILE --> internet
    (no database access here)

INPUTS
    Ids and timestamps chosen by the callers in features/ (see each function).
"""

import logging
import time

import requests

SNAPSHOT_URL = "https://hub.snapshot.org/graphql"
REQUEST_TIMEOUT = 30   # seconds; without a timeout a stalled connection hangs forever
PAGE_SIZE = 1000       # Snapshot's maximum `first`

logger = logging.getLogger(__name__)

# Every proposal field we store; one list so all proposal queries agree.
PROPOSAL_FIELDS = """
    id title body state start end created author choices scores scores_total
    scores_state votes discussion link space { id }
"""
VOTE_FIELDS = "id voter created choice vp reason"


def run_query(query: str) -> dict:
    """
    Send one GraphQL query and return its "data" part.

    Parameter (where it comes from):
        query - a GraphQL string built by one of the functions below.
    Raises RuntimeError if Snapshot reports an error, requests errors on network failure.
    """
    resp = requests.post(SNAPSHOT_URL, json={"query": query}, timeout=REQUEST_TIMEOUT)
    body = resp.json()
    if "errors" in body:
        raise RuntimeError(f"Snapshot GraphQL error: {body['errors']}")
    return body["data"]


def _run_query_retry(query: str, attempts: int = 4, backoff: float = 1.5) -> dict:
    """
    run_query, retried with growing waits (1.5 s, 3 s, 6 s) on network or
    rate-limit errors. Every function in this file goes through here.

    Parameters (where they come from):
        query    - built by the calling function in this file.
        attempts - how many tries in total (default 4).
        backoff  - first wait in seconds; doubles each retry.
    """
    for attempt in range(attempts):
        try:
            return run_query(query)
        except (requests.RequestException, RuntimeError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(backoff * (2 ** attempt))


def _iter_by_created(entity: str, where: str, fields: str, start: int, unique_key: str,
                     label: str, page_size: int = PAGE_SIZE, pause: float = 0.2):
    """
    Time-cursor paging (see HOW PAGING WORKS above). Yields each item once.

    Parameters (where they come from):
        entity     - "votes" or "proposals" (the GraphQL collection).
        where      - the filter, e.g. 'proposal: "0x.."' — set by iter_all_votes /
                     iter_proposals_created_after.
        fields     - VOTE_FIELDS or PROPOSAL_FIELDS.
        start      - first timestamp to include (created_gte).
        unique_key - "voter" for votes (one vote per wallet), "id" for proposals;
                     used to drop the repeats at page boundaries.
        label      - shown in the warning below (a proposal or space id).
        page_size, pause - tests use page_size and pause=0.

    Known limit: if more than `page_size` items share one exact second, the
    cursor cannot move past it. We stop with a warning instead of looping
    forever; for votes, the audit then shows the proposal as 'partial'.
    """
    seen: set[str] = set()
    cursor = start
    while True:
        query = """
        query {
            %s(
                first: %d
                where: { %s, created_gte: %d }
                orderBy: "created"
                orderDirection: asc
            ) { %s }
        }
        """ % (entity, page_size, where, cursor, fields)
        page = _run_query_retry(query)[entity]
        for item in page:
            if item[unique_key] not in seen:       # boundary items come back twice; yield once
                seen.add(item[unique_key])
                yield item

        if len(page) < page_size:
            return                                  # a short page is the last page
        if page[-1]["created"] == cursor:
            # The whole page sits in the cursor's second, so the cursor cannot move.
            logger.warning(f"{label}: over {page_size} {entity} share timestamp {cursor}; "
                           "stopping early, the audit will show this as incomplete")
            return
        cursor = page[-1]["created"]                # always moves forward, so the loop ends
        time.sleep(pause)


def get_space(space_id: str) -> dict | None:
    """
    One DAO's Snapshot info: id, name, about, network and its total
    proposalsCount / followersCount / votesCount. None if the space is unknown.

    Parameter (where it comes from):
        space_id - from config/curated_daos.py, via features/proposals/fetch.py refresh_spaces.
    """
    query = """
    query { space(id: "%s") { id name about network proposalsCount followersCount votesCount } }
    """ % space_id
    return _run_query_retry(query)["space"]


def get_proposals(space_id: str, first: int = 20, skip: int = 0) -> list:
    """
    The newest `first` proposals of a space (after skipping `skip`).

    Parameters (where they come from):
        space_id - from config/curated_daos.py, via features/proposals/fetch.py.
        first    - fetch_new_proposals passes initial_per_dao (default 20) for a
                   DAO that has never been synced.
        skip     - 0 in normal use.
    """
    query = """
    query {
        proposals(first: %d, skip: %d, where: { space: "%s" }, orderBy: "created", orderDirection: desc) {
            %s
        }
    }
    """ % (first, skip, space_id, PROPOSAL_FIELDS)
    return _run_query_retry(query)["proposals"]


def get_proposals_by_ids(proposal_ids: list[str], batch_size: int = 100) -> list[dict]:
    """
    Current data for specific proposals, wherever they sit in the DAO's list.
    Ids Snapshot no longer knows are simply missing from the result.

    Parameters (where they come from):
        proposal_ids - stored proposals that are not finished yet, chosen by
                       features/proposals/fetch.py refresh_unfinished_proposals.
        batch_size   - ids per request (default 100).
    """
    found = []
    for start in range(0, len(proposal_ids), batch_size):
        batch = proposal_ids[start:start + batch_size]
        ids = ", ".join(f'"{i}"' for i in batch)
        query = "query { proposals(first: %d, where: { id_in: [%s] }) { %s } }" % (len(batch), ids, PROPOSAL_FIELDS)
        found.extend(_run_query_retry(query)["proposals"])
    return found


def iter_proposals_created_after(space_id: str, created_after: int, page_size: int = PAGE_SIZE, pause: float = 0.2):
    """
    Every proposal of a space created after `created_after` (unix time), oldest first.

    Parameters (where they come from):
        space_id      - from config/curated_daos.py, via features/proposals/fetch.py.
        created_after - the newest proposals.created_ts we already store for that DAO.
        page_size, pause - defaults in normal use; tests shrink them.
    """
    return _iter_by_created("proposals", f'space: "{space_id}"', PROPOSAL_FIELDS,
                            start=created_after + 1,      # strictly after: start one second later
                            unique_key="id", label=space_id, page_size=page_size, pause=pause)


def iter_all_votes(proposal_id: str, page_size: int = PAGE_SIZE, pause: float = 0.2, start_ts: int = 0):
    """
    Every vote of a proposal, oldest first: {id, voter, created, choice, vp, reason}.

    Parameters (where they come from):
        proposal_id - a proposal whose votes are missing or partial, chosen by
                      features/votes/fetch.py fetch_all_votes.
        start_ts    - the newest stored vote's timestamp, so a re-run downloads only
                      new votes (re-reading that one second is harmless: writes are upserts).
        page_size, pause - defaults in normal use; tests shrink them.
    """
    return _iter_by_created("votes", f'proposal: "{proposal_id}"', VOTE_FIELDS,
                            start=start_ts, unique_key="voter", label=proposal_id,
                            page_size=page_size, pause=pause)


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to the caller, which stores the results in SQLite:
#   features/proposals/fetch.py  (get_space, get_proposals, get_proposals_by_ids,
#                                 iter_proposals_created_after)
#   features/votes/fetch.py      (iter_all_votes)
# If Snapshot is down or rate-limits us: _run_query_retry waits and retries 3 times,
#   then raises; the caller records the failure and moves on to the next DAO/proposal.
