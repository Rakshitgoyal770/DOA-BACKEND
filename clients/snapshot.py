# clients/snapshot.py
import requests

SNAPSHOT_URL = "https://hub.snapshot.org/graphql"


def run_query(query: str) -> dict:
    payload = {"query": query}
    
    resp = requests.post(SNAPSHOT_URL, json=payload)
    
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
    query = """
    query {
        proposals(
            first: %d
            skip: %d
            where: {
                space: "%s"
            }
            orderBy: "created"
            orderDirection: desc
        ) {
            id
            title
            body
            state
            start
            end
            snapshot
            created
            author
            space {
                id
            }
            choices
            scores
            scores_total
            votes
            quorum
            discussion
            link
            type
        }
    }
    """ % (first, skip, space_id)

    data = run_query(query)
    return data["proposals"]



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
    import time

    for attempt in range(attempts):
        try:
            return run_query(query)
        except (requests.RequestException, RuntimeError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(backoff * (2 ** attempt))


def iter_all_votes(proposal_id: str, page_size: int = 1000, pause: float = 0.2, start_ts: int = 0):
    """
    Yields every vote of a proposal, in pages.

    Snapshot caps `first` at 1000 and `skip` at 5000, so plain skip-paging stops
    at ~6000 votes. Instead this moves a cursor over `created` (timestamp): each
    page asks for votes with created >= the last seen timestamp. `>=` (not `>`)
    avoids losing votes that share a timestamp across a page boundary; votes
    already yielded are skipped by voter address. `start_ts` resumes from a timestamp
    (re-fetching the boundary second is harmless because writes are upserts).
    """
    import time

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
        fresh = [v for v in page if v["voter"] not in seen]
        if not fresh:
            return
        for v in fresh:
            seen.add(v["voter"])
            yield v
        if len(page) < page_size:
            return
        cursor = page[-1]["created"]
        time.sleep(pause)

