#!/usr/bin/env bash
# Print dashboard JSON for the public docs page.
# Runs on Luffy. Reads student_repos.json inside CT 200.
# Tokens are used for the GitHub API and are never printed.
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

repos = []
for entry in data:
    if not isinstance(entry, dict):
        continue
    url = (entry.get("repo") or "").strip()
    token = entry.get("token") or ""
    if not url:
        continue
    parts = url.rstrip("/").split("/")
    owner = parts[-2] if len(parts) >= 2 else ""
    name = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    last = None
    note = None
    if token and owner and name:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/%s/commits?path=price_history.json&per_page=100"
            % (owner, name),
            headers={
                "Authorization": "token " + token,
                "Accept": "application/vnd.github+json",
                "User-Agent": "luffy-dashboard",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                commits = json.load(resp)
            if isinstance(commits, list):
                for commit in commits:
                    message = ((commit.get("commit") or {}).get("message") or "")
                    if message.startswith("Update price history"):
                        last = ((commit.get("commit") or {}).get("committer") or {}).get("date")
                        break
        except urllib.error.HTTPError:
            note = "could not read commits"
        except Exception:
            note = "could not read commits"
    row = {
        "username": owner,
        "repo": name,
        "url": ("https://github.com/%s/%s" % (owner, name)) if owner and name else url,
        "last_push": last,
    }
    if note:
        row["note"] = note
    repos.append(row)

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
