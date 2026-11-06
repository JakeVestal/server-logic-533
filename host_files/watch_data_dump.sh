#!/usr/bin/env bash
# Watch /opt/trading/data_dump for new seed CSVs and load them into Robin.
# Requires inotify-tools (apt install inotify-tools).
# Run in the background or under a supervisor.

set -euo pipefail
DUMP_DIR=/opt/trading/data_dump
LOADER=/opt/server-logic-533/host_files/lseg_dump_to_robin.py
VENV_PY=/opt/trading/lseg-venv/bin/python3

mkdir -p "$DUMP_DIR/processed"

echo "Watching $DUMP_DIR for seed CSVs..."
inotifywait -m -e close_write -e moved_to --format '%f' "$DUMP_DIR" | while read -r file; do
  case "$file" in
    identifiers-seed-*.csv|equity-seed-*.csv)
      echo "New file: $file — running loader"
      "$VENV_PY" "$LOADER" || echo "Loader failed for $file"
      ;;
  esac
done
