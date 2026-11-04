#!/usr/bin/env bash
# Ask GitHub Actions to read the repo list on Luffy and publish the dashboard.
# Does not start IB Gateway. Does not print the token.
#
# The token file is a fine-grained PAT for JakeVestal/server-logic-533 only,
# with Actions: Read and write. Nothing else. Create it once:
#
#   umask 077
#   read -r -s -p "dispatch token: " T
#   printf '%s' "$T" > /opt/trading/status_dispatch.token
#   unset T
#   chmod 600 /opt/trading/status_dispatch.token
#
# Without that file, use the button instead:
#   GitHub → Actions → Luffy status → Run workflow
set -euo pipefail

TOKEN_FILE="/opt/trading/status_dispatch.token"
REPO="JakeVestal/server-logic-533"
WORKFLOW="status.yml"

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "No $TOKEN_FILE." >&2
  echo "The Actions button still works: GitHub → Actions → Luffy status → Run workflow." >&2
  exit 1
fi

token=$(tr -d '[:space:]' < "$TOKEN_FILE")
if [[ -z "$token" ]]; then
  echo "Token file is empty: $TOKEN_FILE" >&2
  exit 1
fi

body=$(mktemp)
trap 'rm -f "$body"' EXIT
code=$(curl -sS -o "$body" -w '%{http_code}' \
  -X POST \
  -H "Authorization: Bearer ${token}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches" \
  -d '{"ref":"main"}')
unset token

if [[ "$code" == "204" ]]; then
  echo "Dashboard refresh requested."
  echo "https://github.com/${REPO}/actions/workflows/${WORKFLOW}"
  exit 0
fi

echo "GitHub dispatch failed (HTTP ${code})." >&2
cat "$body" >&2
exit 1
