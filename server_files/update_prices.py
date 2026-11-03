#!/usr/bin/env python3
"""
Fetch price_history.json from each subscribed repo,
update tracked contracts via IB Gateway,
and push the updated file back.

Supports per-repo tokens via /opt/trading/student_repos.json.
Falls back to the legacy single-token + subscribed_repos.txt path
if that file is absent.
"""

import json
import base64
import requests
from datetime import datetime, timedelta
from ib_insync import IB, Contract

STUDENT_REPOS_FILE = "/opt/trading/student_repos.json"
LEGACY_TOKEN_FILE = "/opt/trading/github_token"
LEGACY_REPOS_FILE = "/opt/trading/subscribed_repos.txt"

IB_HOST = "127.0.0.1"
IB_PORT = 4002
CLIENT_ID = 1


def owner_repo(url):
    parts = url.strip().rstrip("/").split("/")
    return parts[-2], parts[-1].replace(".git", "")


def load_targets():
    """
    Return a list of (owner, repo, token) tuples.
    Prefers student_repos.json; falls back to legacy files.
    """
    targets = []

    try:
        with open(STUDENT_REPOS_FILE) as f:
            entries = json.load(f)
        for e in entries:
            repo_url = e.get("repo", "").strip()
            token = e.get("token", "").strip()
            if not repo_url or not token:
                continue
            owner, repo = owner_repo(repo_url)
            targets.append((owner, repo, token))
        if targets:
            print(f"Loaded {len(targets)} repos from {STUDENT_REPOS_FILE}")
            return targets
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        print(f"WARNING: {STUDENT_REPOS_FILE} is not valid JSON: {exc}")

    # Legacy fallback
    try:
        token = open(LEGACY_TOKEN_FILE).read().strip()
    except FileNotFoundError:
        print("ERROR: no student_repos.json and no github_token")
        return []

    try:
        with open(LEGACY_REPOS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    owner, repo = owner_repo(line)
                    targets.append((owner, repo, token))
    except FileNotFoundError:
        print(f"ERROR: {LEGACY_REPOS_FILE} not found")
        return []

    print(f"Loaded {len(targets)} repos from legacy files")
    return targets


def gh_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_file(owner, repo, path, token):
    r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=gh_headers(token),
    )
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]


def put_file(owner, repo, path, content, sha, message, token):
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "sha": sha,
    }
    r = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=gh_headers(token),
        json=payload,
    )
    r.raise_for_status()


def main():
    targets = load_targets()
    if not targets:
        print("No repos to process")
        return

    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID)

    for owner, repo, token in targets:
        print(f"Processing {owner}/{repo}")
        try:
            data, sha = get_file(owner, repo, "price_history.json", token)
        except Exception as exc:
            print(f"  ERROR reading price_history.json: {exc}")
            continue

        changed = False
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
            changed = True

        if not changed:
            print("  no updates needed")
            continue

        updated = json.dumps(data, indent=2)
        try:
            put_file(
                owner, repo, "price_history.json", updated, sha,
                f"Update price history {datetime.now():%Y-%m-%d}",
                token,
            )
            print("  pushed updated price_history.json")
        except Exception as exc:
            print(f"  ERROR pushing: {exc}")

    ib.disconnect()


if __name__ == "__main__":
    main()
