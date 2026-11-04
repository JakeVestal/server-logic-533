#!/usr/bin/env bash
# Apply robin/schema.sql to the robin database on CT 201.
# Run once on Luffy, after this repo has been pulled to /opt/server-logic-533:
#   /opt/trading/apply_robin_schema.sh
# Refuses if price_bars already has rows. Override with --force.
# Prompts for the robin_writer password unless ROBIN_WRITER_PASSWORD is set.
# The password is not written to the repo.

set -euo pipefail

CTID=201
SCHEMA="${SCHEMA:-/opt/server-logic-533/robin/schema.sql}"
FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

if [[ ! -f "$SCHEMA" ]]; then
  echo "schema not found: $SCHEMA" >&2
  echo "Push the repo and let the deploy finish, then run this again." >&2
  exit 1
fi

if ! pct status "$CTID" 2>/dev/null | grep -q running; then
  echo "CT $CTID is not running" >&2
  exit 1
fi

# Postgres plans every table named in a query before it runs the CASE,
# so "count(*) FROM price_bars" errors when the table was never created
# (the first apply dropped it, then failed). Ask whether it exists first.
reg=$(pct exec "$CTID" -- su - postgres -c \
  "psql -d robin -tAc \"SELECT to_regclass('public.price_bars')\"")
reg=$(printf '%s' "$reg" | tr -d '[:space:]')
if [[ -z "$reg" ]]; then
  existing=-1
else
  existing=$(pct exec "$CTID" -- su - postgres -c \
    "psql -d robin -tAc \"SELECT count(*) FROM price_bars\"")
  existing=$(printf '%s' "$existing" | tr -d '[:space:]')
fi

if [[ "$existing" != "-1" && "$existing" != "0" && "$FORCE" -ne 1 ]]; then
  echo "public.price_bars has ${existing} rows. Refusing to drop them." >&2
  echo "Re-run with --force only if you mean to destroy that data." >&2
  exit 1
fi

remote_schema=/tmp/robin-schema.sql
remote_pw=/tmp/robin-writer-pw.sql
cleanup() {
  pct exec "$CTID" -- rm -f "$remote_schema" "$remote_pw" || true
}
trap cleanup EXIT

echo "Applying $SCHEMA on CT $CTID (database robin)"
pct push "$CTID" "$SCHEMA" "$remote_schema"
pct exec "$CTID" -- su - postgres -c \
  "psql -d robin -v ON_ERROR_STOP=1 -f $remote_schema"

if [[ -z "${ROBIN_WRITER_PASSWORD:-}" ]]; then
  read -r -s -p "Set robin_writer password: " ROBIN_WRITER_PASSWORD
  echo
fi
if [[ -z "${ROBIN_WRITER_PASSWORD}" ]]; then
  echo "No password given. Schema is applied, but robin_writer has no password yet." >&2
  exit 1
fi

umask 077
pw_file=$(mktemp)
python3 - "$ROBIN_WRITER_PASSWORD" > "$pw_file" << 'PY'
import sys
pw = sys.argv[1].replace("'", "''")
print(f"ALTER ROLE robin_writer PASSWORD '{pw}';")
PY
unset ROBIN_WRITER_PASSWORD
pct push "$CTID" "$pw_file" "$remote_pw"
rm -f "$pw_file"
# pct push keeps the host mode (600, root). postgres must own it or psql cannot read it.
pct exec "$CTID" -- chown postgres:postgres "$remote_pw"
pct exec "$CTID" -- chmod 600 "$remote_pw"
pct exec "$CTID" -- su - postgres -c \
  "psql -d robin -v ON_ERROR_STOP=1 -f $remote_pw"

echo "Robin schema applied."
echo "  student_ro:    SELECT"
echo "  robin_writer:  SELECT, INSERT, UPDATE"
