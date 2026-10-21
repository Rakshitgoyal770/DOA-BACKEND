# clients/ens.py
"""ENS lookups in both directions via the free ensideas API."""

import requests

ENS_URL = "https://api.ensideas.com/ens/resolve/{query}"
USER_AGENT = "Mozilla/5.0 (compatible; DAOGovernanceResearch/0.1)"


def get_ens_name(wallet_address: str) -> str | None:
    """Reverse lookup: wallet -> primary ENS name, or None if it has none."""
    resp = requests.get(ENS_URL.format(query=wallet_address), timeout=10,
                        headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        return None
    return resp.json().get("name")


def resolve_ens_name(name: str) -> str | None:
    """Forward lookup: 'slobo.eth' -> wallet address, or None. Never raises on network errors."""
    try:
        resp = requests.get(ENS_URL.format(query=name), timeout=10,
                            headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return None
        return resp.json().get("address")
    except (requests.RequestException, ValueError):
        return None


if __name__ == "__main__":
    # vitalik.eth's known address
    print(get_ens_name("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"))
