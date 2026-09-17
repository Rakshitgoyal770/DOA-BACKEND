# resolution/ens_client.py
import requests

def get_ens_name(wallet_address: str) -> str | None:
    """Returns the ENS name for a wallet, or None if it has none."""
    url = f"https://api.ensideas.com/ens/resolve/{wallet_address}"
    resp = requests.get(url, timeout=10)
    
    if resp.status_code != 200:
        return None
    
    data = resp.json()
    return data.get("name")


if __name__ == "__main__":
    # test with vitalik.eth's known address
    name = get_ens_name("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    print(name)