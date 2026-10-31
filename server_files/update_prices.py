#!/usr/bin/env python3
"""
Fetch price_history.json from each subscribed repo,
update tracked contracts via IB Gateway,
and push the updated file back.
"""

import json
import base64
import requests
from datetime import datetime, timedelta
from ib_insync import IB, Contract

TOKEN = open("/opt/trading/github_token").read().strip()
REPOS_FILE = "/opt/trading/subscribed_repos.txt"
IB_HOST = "127.0.0.1"
IB_PORT = 4002
CLIENT_ID = 1

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

def owner_repo(url):
    parts = url.strip().rstrip("/").split("/")
    return parts[-2], parts[-1].replace(".git", "")

def get_file(owner, repo, path):
    r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=HEADERS,
    )
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]

def put_file(owner, repo, path, content, sha, message):
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "sha": sha,
    }
    r = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=HEADERS,
        json=payload,
    )
    r.raise_for_status()

def main():
    repos = []
    with open(REPOS_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                repos.append(line)

    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID)

    for url in repos:
        owner, repo = owner_repo(url)
        print(f"Processing {owner}/{repo}")

        data, sha = get_file(owner, repo, "price_history.json")

        for conid, info in data.items():
            if not info.get("tracked"):
                continue

            contract = Contract(conId=int(conid))
            ib.qualifyContracts(contract)

            history = info.get("price_history", {})
            if history:
                last = max(history.keys())
                start = datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)
            else:
                start = datetime.now() - timedelta(days=30)

            end = datetime.now()
            if start.date() >= end.date():
                print(f"  {conid}: up to date")
                continue

            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end,
                durationStr=f"{(end - start).days + 1} D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )

            for bar in bars:
                date_str = bar.date.strftime("%Y-%m-%d")
                history[date_str] = {
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            info["price_history"] = history

        updated = json.dumps(data, indent=2)
        put_file(
            owner, repo, "price_history.json", updated, sha,
            f"Update price history {datetime.now():%Y-%m-%d}",
        )
        print(f"  pushed updated price_history.json")

    ib.disconnect()

if __name__ == "__main__":
    main()
