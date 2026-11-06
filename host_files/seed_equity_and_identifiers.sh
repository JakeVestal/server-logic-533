#!/usr/bin/env bash
# Batch LSEG equity seed. Takes any number of RICs, splits into groups of 25,
# calls seed_equity_and_identifiers, and writes CSVs to /opt/trading/data_dump.
#
# Files:
#   identifiers-seed-N.csv   reference data
#   equity-seed-N.csv        daily history
#
# Usage: seed_equity_and_identifiers.sh RIC [RIC ...]
# Example: seed_equity_and_identifiers.sh AAPL.O MSFT.O TSLA.O

set -euo pipefail

DUMP_DIR=/opt/trading/data_dump
CRED_DIR=/opt/trading
APP_KEY_FILE="$CRED_DIR/lseg_app_key"
USERNAME_FILE="$CRED_DIR/lseg_username"
PASSWORD_FILE="$CRED_DIR/lseg_password"

for f in "$APP_KEY_FILE" "$USERNAME_FILE" "$PASSWORD_FILE"; do
  if [[ ! -r "$f" ]]; then
    echo "ERROR: missing or unreadable $f" >&2
    exit 1
  fi
done

mkdir -p "$DUMP_DIR"
chmod 700 "$DUMP_DIR"

export LSEG_APP_KEY="$(<"$APP_KEY_FILE")"
export LSEG_USERNAME="$(<"$USERNAME_FILE")"
export LSEG_PASSWORD="$(<"$PASSWORD_FILE")"

# Locate the Python module
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/seed_equity_and_identifiers.py"
if [[ ! -f "$PY" ]]; then
  PY="/opt/server-logic-533/host_files/seed_equity_and_identifiers.py"
fi
if [[ ! -f "$PY" ]]; then
  echo "ERROR: cannot find seed_equity_and_identifiers.py" >&2
  exit 1
fi

# Next incremental number
next_num() {
  local max=0
  local f
  for f in "$DUMP_DIR"/identifiers-seed-*.csv "$DUMP_DIR"/equity-seed-*.csv; do
    [[ -e "$f" ]] || continue
    local n
    n=$(basename "$f" .csv | sed 's/.*-//')
    if [[ "$n" =~ ^[0-9]+$ ]] && (( n > max )); then
      max=$n
    fi
  done
  echo $((max + 1))
}

# Batch and run
rics=("$@")
if (( ${#rics[@]} == 0 )); then
  echo "Usage: $0 RIC [RIC ...]" >&2
  exit 2
fi

batch_size=5
total=${#rics[@]}
echo "Seeding $total RIC(s) in batches of $batch_size"

i=0
while (( i < total )); do
  batch=("${rics[@]:i:batch_size}")
  n=$(next_num)
  echo "Batch $((i/batch_size + 1)): ${#batch[@]} RIC(s) → identifiers-seed-$n.csv / equity-seed-$n.csv"

  /opt/trading/lseg-venv/bin/python3 - "$PY" "$DUMP_DIR" "$n" "${batch[@]}" << 'PY'
import sys
py_path, dump_dir, n = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, py_path.rsplit("/", 1)[0])
from seed_equity_and_identifiers import seed_equity_and_identifiers
rics = sys.argv[4:]
ref, hist = seed_equity_and_identifiers(rics)
ref.to_csv(f"{dump_dir}/identifiers-seed-{n}.csv", index=False)
hist.to_csv(f"{dump_dir}/equity-seed-{n}.csv")
print(f"Wrote identifiers-seed-{n}.csv ({len(ref)} rows) and equity-seed-{n}.csv ({len(hist)} rows)")
PY

  i=$((i + batch_size))
  # Pace between batches to stay well under 5 req/s and daily volume
  if (( i < total )); then
    echo "Pacing 2s before next batch..."
    sleep 2
  fi
done

echo "Done. Files in $DUMP_DIR"
