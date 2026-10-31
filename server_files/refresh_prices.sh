#!/usr/bin/env bash
# Full price refresh: start IB Gateway via IBC, run update_prices.py, stop Gateway.
# Intended to run on the host that has the IBG container (or inside the container).
set -euo pipefail

CTID=200
IBG_USER=ibgateway
LOG_DIR=/home/${IBG_USER}/ibc/logs

log() { echo "[$(date +'%H:%M:%S')] $*"; }

log "Starting IB Gateway (CT $CTID)..."
pct exec "$CTID" -- su - "$IBG_USER" -c '
  export DISPLAY=:99
  # Start Xvfb if not already running
  if ! pgrep -f "Xvfb :99" >/dev/null; then
    Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
    sleep 1
  fi
  # Start IBC/Gateway in background
  nohup /opt/ibc/gatewaystart.sh -inline >/tmp/ibg-start.log 2>&1 &
'

log "Waiting for Gateway API on port 4002..."
for i in {1..60}; do
  if pct exec "$CTID" -- ss -tlnp | grep -q ':4002'; then
    log "Gateway ready."
    break
  fi
  sleep 2
done

log "Running price update..."
pct exec "$CTID" -- /opt/trading/update_prices.py || log "update_prices.py exited with error"

log "Stopping IB Gateway..."
pct exec "$CTID" -- su - "$IBG_USER" -c '
  # Find and kill the IBC/Gateway Java process
  pkill -f "ibcalpha.ibc.IbcGateway" || true
  pkill -f "Xvfb :99" || true
'

log "Refresh complete."
log "Latest IBC log:"
pct exec "$CTID" -- bash -c "ls -t $LOG_DIR/ibc-*.txt | head -1 | xargs tail -20" || true
