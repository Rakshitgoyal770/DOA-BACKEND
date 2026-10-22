# clients/snapshot.py
import logging
import time

import requests

SNAPSHOT_URL = "https://hub.snapshot.org/graphql"
REQUEST_TIMEOUT = 30   # seconds; without a timeout a stalled connection hangs forever

logger = logging.getLogger(__name__)

# Every proposal field we store; one list so all proposal queries agree.
PROPOSAL_FIELDS = """
    id title body state start end created author choices scores scores_total
    scores_state votes discussion link space { id }
"""


def run_query(query: str) -> dict:
    payload = {"query": query}
    
    resp = requests.post(SNAPSHOT_URL, json=payload, timeout=REQUEST_TIMEOUT)
    
    body = resp.json()
    
    if "errors" in body:
        raise RuntimeError(f"Snapshot GraphQL error: {body['errors']}")
    
    return body["data"]




def get_space(space_id: str) -> dict:
    query = """
    query {
        space(id: "%s") {
            id
            name
            about
            network
            symbol
            avatar
            website
            twitter
        }
    }
    """ % space_id

    data = run_query(query)

    return data["space"]




def get_proposals(space_id: str, first: int = 20, skip: int = 0) -> list:
    """The newest `first` proposals of a space (after skipping `skip`)."""
    query = """
    query {
        proposals(first: %d, skip: %d, where: { space: "%s" }, orderBy: "created", orderDirection: desc) {
            %s
        }
    }
    """ % (first, skip, space_id, PROPOSAL_FIELDS)
    return _run_query_retry(query)["proposals"]


def get_votes(proposal_id: str, first: int = 100, skip: int = 0) -> list:
    query = """
    query {
        votes(
            first: %d
            skip: %d
            where: {
                proposal: "%s"
            }
            orderBy: "created"
            orderDirection: asc
        ) {
            id
            voter
            created
            choice
            vp
            reason
            space {
                id
            }
            proposal {
                id
            }
        }
    }
    """ % (first, skip, proposal_id)

    data = run_query(query)

    return data["votes"]


def _run_query_retry(query: str, attempts: int = 4, backoff: float = 1.5) -> dict:
    """run_query with exponential backoff for transient network/rate-limit errors."""
    for attempt in range(attempts):
        try:
            return run_query(query)
        except (requests.RequestException, RuntimeError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(backoff * (2 ** attempt))


def get_proposals_by_ids(proposal_ids: list[str], batch_size: int = 100) -> list[dict]:
    """Current data for specific proposals, wherever they sit in the space's list."""
    found = []
    for start in range(0, len(proposal_ids), batch_size):
        batch = proposal_ids[start:start + batch_size]
        ids = ", ".join(f'"{i}"' for i in batch)
        query = "query { proposals(first: %d, where: { id_in: [%s] }) { %s } }" % (len(batch), ids, PROPOSAL_FIELDS)
        found.extend(_run_query_retry(query)["proposals"])
    return found


def iter_proposals_created_after(space_id: str, created_after: int, page_size: int = 1000, pause: float = 0.2):
    """
    Yields every proposal of a space created after `created_after` (unix time),
    oldest first. Same cursor paging as iter_all_votes: no "latest N" window,
    no skip limit, and proposals sharing a second are not lost.
    """
    seen: set[str] = set()
    cursor = created_after + 1          # created_gte, so start one second later
    while True:
        query = """
        query {
            proposals(
                first: %d
                where: { space: "%s", created_gte: %d }
                orderBy: "created"
                orderDirection: asc
            ) { %s }
        }
        """ % (page_size, space_id, cursor, PROPOSAL_FIELDS)
        page = _run_query_retry(query)["proposals"]
        for p in page:
            if p["id"] not in seen:
                seen.add(p["id"])
                yield p
        if len(page) < page_size:
            return
        if page[-1]["created"] == cursor:
            logger.warning(f"{space_id}: over {page_size} proposals share timestamp {cursor}; stopping early")
            return
        cursor = page[-1]["created"]
        time.sleep(pause)


def iter_all_votes(proposal_id: str, page_size: int = 1000, pause: float = 0.2, start_ts: int = 0):
    """
    Yields every vote of a proposal, in pages.

    Snapshot caps `first` at 1000 and `skip` at 5000, so plain skip-paging stops
    at ~6000 votes. Instead this moves a cursor over `created` (timestamp): each
    page asks for votes with created >= the last seen timestamp. `>=` (not `>`)
    avoids losing votes that share a timestamp across a page boundary; votes
    already yielded are skipped by voter address. `start_ts` resumes from a timestamp
    (re-fetching the boundary second is harmless because writes are upserts).

    Known limit: if more than `page_size` votes share one exact second, the
    cursor cannot move past that second. We then stop with a warning; the
    proposal stays 'partial' in the audit instead of looping forever.
    """
    seen: set[str] = set()
    cursor = start_ts
    while True:
        query = """
        query {
            votes(
                first: %d
                where: { proposal: "%s", created_gte: %d }
                orderBy: "created"
                orderDirection: asc
            ) { id voter created choice vp reason }
        }
        """ % (page_size, proposal_id, cursor)
        page = _run_query_retry(query)["votes"]
        for v in page:
            if v["voter"] not in seen:              # boundary votes come back twice; yield once
                seen.add(v["voter"])
                yield v

        if len(page) < page_size:
            return                                  # a short page is the last page
        if page[-1]["created"] == cursor:
            # The whole page sits in the cursor's second, so the cursor cannot move.
            logger.warning(f"{proposal_id}: over {page_size} votes share timestamp {cursor}; "
                           "stopping early, the audit will show this proposal as partial")
            return
        cursor = page[-1]["created"]                # always moves forward, so the loop ends
        time.sleep(pause)

