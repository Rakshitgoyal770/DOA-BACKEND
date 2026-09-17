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

