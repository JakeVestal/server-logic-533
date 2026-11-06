#!/usr/bin/env bash
# Watch /opt/trading/data_dump for seed CSVs and load them into Robin.
# On start, first process any files already present (survives reboot / power loss).
# Then watch for new ones via inotify.
# Requires inotify-tools.

set -euo pipefail
DUMP_DIR=/opt/trading/data_dump
LOADER=/opt/server-logic-533/host_files/lseg_dump_to_robin.py
VENV_PY=/opt/trading/lseg-venv/bin/python3

mkdir -p "$DUMP_DIR/processed"

run_loader() {
  echo "[$(date +'%H:%M:%S')] Running loader..."
  if "$VENV_PY" "$LOADER"; then
    echo "[$(date +'%H:%M:%S')] Loader finished"
  else
    echo "[$(date +'%H:%M:%S')] Loader failed — leaving files in place" >&2
  fi
}

# Drain anything already there
if ls "$DUMP_DIR"/*-seed-*.csv >/dev/null 2>&1; then
  echo "[$(date +'%H:%M:%S')] Existing CSVs found — draining"
  run_loader
fi

echo "[$(date +'%H:%M:%S')] Watching $DUMP_DIR for new seed CSVs..."
inotifywait -m -e close_write -e moved_to --format '%f' "$DUMP_DIR" | while read -r file; do
  case "$file" in
    identifiers-seed-*.csv|equity-seed-*.csv)
      echo "[$(date +'%H:%M:%S')] New file: $file"
      run_loader
      ;;
  esac
done
