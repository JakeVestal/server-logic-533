#!/usr/bin/env bash
# Replace the PAT for one repo in CT 200 /opt/trading/student_repos.json.
# Ask for a search string, make the operator pick one repo, then read the new PAT.
# Unlike delete_repo.sh, a broad search never changes more than the one repo picked.
# After the write, the token is read back from disk and printed masked.
set -euo pipefail

CTID=200
FILE=/opt/trading/student_repos.json

if ! pct exec "$CTID" -- test -f "$FILE" 2>/dev/null; then
  echo "No student_repos.json found in CT$CTID" >&2
  exit 1
fi

read -rp "Find repo (username, repo name, or URL): " query
query="${query//[[:space:]]/}"
if [[ -z "$query" ]]; then
  echo "ERROR: empty search" >&2
  exit 1
fi

list=$(mktemp)
trap 'rm -f "$list"' EXIT

set +e
pct exec "$CTID" -- env QUERY="$query" python3 - << 'PY' >"$list"
import json, os, sys
path = "/opt/trading/student_repos.json"
q = os.environ["QUERY"].lower()
try:
    with open(path) as f:
        data = json.load(f)
except json.JSONDecodeError as exc:
    print(f"ERROR: student_repos.json is not valid JSON: {exc}", file=sys.stderr)
    sys.exit(1)
if not isinstance(data, list):
    print("ERROR: student_repos.json is not a list", file=sys.stderr)
    sys.exit(1)
seen = []
for entry in data:
    if not isinstance(entry, dict):
        continue
    repo = (entry.get("repo") or "").strip()
    if repo and q in repo.lower() and repo not in seen:
        seen.append(repo)
        print(repo)
if not seen:
    sys.exit(2)
PY
status=$?
set -e

if [[ "$status" -eq 2 ]]; then
  echo "No match. That repo is not on the list."
  echo "Add it with /opt/trading/add_repo.sh"
  exit 1
fi
if [[ "$status" -ne 0 ]]; then
  echo "ERROR: could not read the repo list (exit $status)" >&2
  exit "$status"
fi

mapfile -t matches < "$list"
if [[ "${#matches[@]}" -eq 0 ]]; then
  echo "No match. That repo is not on the list."
  echo "Add it with /opt/trading/add_repo.sh"
  exit 1
fi

echo
echo "Matches:"
for i in "${!matches[@]}"; do
  printf '  %d) %s\n' "$((i + 1))" "${matches[$i]}"
done
echo

if [[ "${#matches[@]}" -eq 1 ]]; then
  choice=1
else
  read -rp "Which number: " choice
fi

if [[ ! "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#matches[@]} )); then
  echo "Not a match number." >&2
  exit 1
fi

repo="${matches[$((choice - 1))]}"
repo="${repo%$'\r'}"
echo "Updating: $repo"
read -rsp "New PAT: " token
echo
token="${token//[[:space:]]/}"
if [[ -z "$token" ]]; then
  echo "ERROR: empty token. No change made." >&2
  exit 1
fi

pct exec "$CTID" -- env REPO="$repo" TOKEN="$token" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
repo = os.environ["REPO"].rstrip("/")
token = os.environ["TOKEN"]
with open(path) as f:
    data = json.load(f)
updated = 0
for entry in data:
    if not isinstance(entry, dict):
        continue
    current = (entry.get("repo") or "").rstrip("/")
    if current == repo:
        entry["token"] = token
        updated += 1
if updated != 1:
    print(f"ERROR: expected 1 entry, found {updated}. No file written.", file=sys.stderr)
    sys.exit(1)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"Updated: {repo}")
PY
unset token

pct exec "$CTID" -- chmod 600 "$FILE"
echo "Permissions set to 600"
pct exec "$CTID" -- env REPO="$repo" python3 - << 'PY'
import json, os, sys
path = "/opt/trading/student_repos.json"
repo = os.environ["REPO"].rstrip("/")
with open(path) as f:
    data = json.load(f)
token = None
for entry in data:
    if not isinstance(entry, dict):
        continue
    current = (entry.get("repo") or "").rstrip("/")
    if current == repo:
        token = entry.get("token") or ""
        break
if token is None:
    print("ERROR: repo not found when reading the token back.", file=sys.stderr)
    sys.exit(1)
if len(token) > 12:
    masked = token[:7] + "..." + token[-4:]
else:
    masked = "***"
print(f"Token on disk: {masked}")
PY
echo "The dashboard mark changes after the next status run:"
echo "  /opt/trading/publish_status.sh"
