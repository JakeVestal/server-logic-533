#!/usr/bin/env bash
# Add a repo + PAT to CT200 /opt/trading/student_repos.json
set -euo pipefail

CTID=200
FILE=/opt/trading/student_repos.json

read -rp "Repo URL: " repo
read -rsp "PAT: " token
echo

repo="${repo//[[:space:]]/}"
token="${token//[[:space:]]/}"

if [[ -z "$repo" || -z "$token" ]]; then
  echo "ERROR: both URL and token are required"
  exit 1
fi

# Basic URL sanity check
if [[ ! "$repo" =~ ^https://github\.com/[^/]+/[^/]+ ]]; then
  echo "WARNING: does not look like a github.com repo URL: $repo"
  read -rp "Continue anyway? [y/N] " yn
  [[ "$yn" == "y" || "$yn" == "Y" ]] || exit 1
fi

# Pass values via environment to the remote python
pct exec "$CTID" -- env REPO="$repo" TOKEN="$token" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
repo = os.environ["REPO"]
token = os.environ["TOKEN"]

try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = []
except json.JSONDecodeError as e:
    print(f"ERROR: existing file is not valid JSON: {e}", file=sys.stderr)
    sys.exit(1)

# Reject exact duplicate URL
for e in data:
    if e.get("repo", "").rstrip("/") == repo.rstrip("/"):
        print(f"ERROR: already subscribed: {repo}", file=sys.stderr)
        sys.exit(1)

data.append({"repo": repo, "token": token})

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print(f"Added: {repo}")
print(f"Total: {len(data)}")
PY

# Lock down permissions
pct exec "$CTID" -- chmod 600 "$FILE"
echo "Permissions set to 600"
