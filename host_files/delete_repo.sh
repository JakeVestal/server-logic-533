#!/usr/bin/env bash
# Search and remove entries from CT200 /opt/trading/student_repos.json
set -euo pipefail

CTID=200
FILE=/opt/trading/student_repos.json

if ! pct exec "$CTID" -- test -f "$FILE" 2>/dev/null; then
  echo "No student_repos.json found in CT$CTID"
  exit 1
fi

read -rp "Search string (matched against repo URL): " query
query="${query//[[:space:]]/}"
if [[ -z "$query" ]]; then
  echo "ERROR: empty search"
  exit 1
fi

echo
echo "Matches:"
pct exec "$CTID" -- env QUERY="$query" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
q = os.environ["QUERY"].lower()
with open(path) as f:
    data = json.load(f)
matches = [e for e in data if q in e.get("repo", "").lower()]
if not matches:
    print("(none)")
    sys.exit(2)
for e in matches:
    print(f"  - {e.get('repo')}")
print(f"\n{len(matches)} match(es)")
PY
status=$?
if [[ $status -eq 2 ]]; then
  exit 0
fi

echo
read -rp "Delete these entries? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted"
  exit 0
fi

pct exec "$CTID" -- env QUERY="$query" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
q = os.environ["QUERY"].lower()
with open(path) as f:
    data = json.load(f)
kept = [e for e in data if q not in e.get("repo", "").lower()]
removed = len(data) - len(kept)
with open(path, "w") as f:
    json.dump(kept, f, indent=2)
    f.write("\n")
print(f"Removed {removed} entries. {len(kept)} remaining.")
PY

pct exec "$CTID" -- chmod 600 "$FILE"
