#!/usr/bin/env bash
# Nami: Saturday shopping-list manager.
# Removes completed rows and (stub) far-OTM / far-dated.
# Discovery of new strikes is stubbed until the chain query is tested.

set -euo pipefail
echo "[$(date +'%H:%M:%S')] Nami: shopping-list maintenance"

pct exec 201 -- su - postgres -c "psql -d robin -c \"
DELETE FROM options_shopping_list
WHERE p_untracked = FALSE AND c_untracked = FALSE;
\""
echo "  removed completed rows (both flags FALSE)"

# TODO: discover new expiries/strikes via LSEG and insert
# TODO: delete far-OTM / far-dated per rules

echo "[$(date +'%H:%M:%S')] Nami: done"
