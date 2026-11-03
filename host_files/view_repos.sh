#!/usr/bin/env bash
# Print subscribed repos from CT200 /opt/trading/student_repos.json
# Tokens are masked.
set -euo pipefail

CTID=200
FILE=/opt/trading/student_repos.json

if ! pct exec "$CTID" -- test -f "$FILE" 2>/dev/null; then
  echo "No student_repos.json found in CT$CTID"
  exit 1
fi

pct exec "$CTID" -- python3 - << 'PY'
import json
path = "/opt/trading/student_repos.json"
with open(path) as f:
    data = json.load(f)
if not data:
    print("(empty)")
    raise SystemExit(0)
print(f"{len(data)} subscribed repos:\n")
for i, e in enumerate(data, 1):
    repo = e.get("repo", "")
    token = e.get("token", "")
    if len(token) > 12:
        masked = token[:7] + "..." + token[-4:]
    else:
        masked = "***"
    print(f"  {i}. {repo}")
    print(f"     token: {masked}")
PY
