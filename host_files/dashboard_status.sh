#!/usr/bin/env bash
# Print dashboard JSON for the public docs page.
# Runs on Luffy. Reads student_repos.json inside CT 200.
# Tokens are used for the GitHub API and are never printed.
# Does not start IB Gateway.
#
# connected is true only when the stored token can write to that repo.
# The check posts one tiny git blob and does not create a commit, so
# nothing new appears in the student's history.
set -euo pipefail

CTID=200

pct exec "$CTID" -- python3 - << 'PY'
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

path = "/opt/trading/student_repos.json"
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = []

if not isinstance(data, list):
    data = []


def github(method, url, token, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": "token " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "luffy-dashboard",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp), resp.status
    except urllib.error.HTTPError as exc:
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if exc.code in (403, 429) and remaining == "0":
            raise SystemExit("GitHub rate limit; status not updated")
        return None, exc.code
    except Exception:
        return None, 0


repos = []
for entry in data:
    if not isinstance(entry, dict):
        continue
    url = (entry.get("repo") or "").strip()
    token = (entry.get("token") or "").strip()
    if not url:
        continue
    parts = url.rstrip("/").split("/")
    owner = parts[-2] if len(parts) >= 2 else ""
    name = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    connected = False
    last = None
    if token and owner and name:
        _blob, code = github(
            "POST",
            "https://api.github.com/repos/%s/%s/git/blobs" % (owner, name),
            token,
            {"content": "luffy-dashboard-permission-check", "encoding": "utf-8"},
        )
        connected = code in (200, 201)
        commits, _code = github(
            "GET",
            "https://api.github.com/repos/%s/%s/commits?path=price_history.json&per_page=100"
            % (owner, name),
            token,
        )
        if isinstance(commits, list):
            for commit in commits:
                message = ((commit.get("commit") or {}).get("message") or "")
                if message.startswith("Update price history"):
                    last = ((commit.get("commit") or {}).get("committer") or {}).get("date")
                    break
    repos.append({
        "username": owner,
        "repo": name,
        "url": ("https://github.com/%s/%s" % (owner, name)) if owner and name else url,
        "last_push": last,
        "connected": connected,
    })

out = {
    "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "ok": True,
    "host": "luffy",
    "repos": repos,
}
print("===DASHBOARD_JSON_START===")
print(json.dumps(out, indent=2))
print("===DASHBOARD_JSON_END===")
PY
