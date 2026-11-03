#!/usr/bin/env bash
# Remove a repo from CT200 /opt/trading/student_repos.json
set -euo pipefail

CTID=200
FILE=/opt/trading/student_repos.json

read -rp "Repo URL to remove: " repo
repo="${repo//[[:space:]]/}"

if [[ -z "$repo" ]]; then
  echo "ERROR: URL is required"
  exit 1
fi

# Pass value via environment to the remote python
pct exec "$CTID" -- env REPO="$repo" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
repo = os.environ["REPO"].rstrip("/")

try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    print("No student_repos.json found — nothing to remove.")
    sys.exit(0)
except json.JSONDecodeError as e:
    print(f"ERROR: existing file is not valid JSON: {e}", file=sys.stderr)
    sys.exit(1)

original_len = len(data)
data = [e for e in data if e.get("repo", "").rstrip("/") != repo]

if len(data) == original_len:
    print(f"Not found: {repo}")
    print("No changes made.")
    sys.exit(0)

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print(f"Removed: {repo}")
print(f"Remaining: {len(data)}")
PY

# Lock down permissions
pct exec "$CTID" -- chmod 600 "$FILE"
echo "Permissions set to 600"
