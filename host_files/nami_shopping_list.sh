#!/usr/bin/env bash
# Nami: Saturday shopping-list manager.
# Discovers new strikes/expiries, removes far-OTM / far-dated, deletes completed rows.
# Discovery call is stubbed until the chain query is tested.

set -euo pipefail
echo "[$(date +'%H:%M:%S')] Nami: shopping-list maintenance"
echo "  (discovery stubbed — implement LSEG chain query next)"
# TODO: query LSEG for available expiries/strikes per tracked underlying
# TODO: insert new rows with both flags TRUE
# TODO: delete rows too far OTM or too far dated (rules TBD)
# TODO: delete rows where p_untracked = FALSE AND c_untracked = FALSE
echo "[$(date +'%H:%M:%S')] Nami: done (stub)"
