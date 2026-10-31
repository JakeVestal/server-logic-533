#!/usr/bin/env bash
# Full price refresh: start IB Gateway via IBC, run update_prices.py, stop Gateway.
# Robust against cold starts / reboots.
set -euo pipefail

CTID=200
IBG_USER=ibgateway
LOG_DIR=/home/${IBG_USER}/ibc/logs
MAX_WAIT_SECS=300   # 5 minutes for Gateway to become ready

log() { echo "[$(date +'%H:%M:%S')] $*"; }

dump_diagnostics() {
  log "=== Diagnostics ==="
  log "--- processes ---"
  pct exec "$CTID" -- ps aux | grep -E 'Xvfb|ibc|java|gateway' | grep -v grep || log "(none)"
  log "--- /tmp/ibg-start.log ---"
  pct exec "$CTID" -- cat /tmp/ibg-start.log 2>/dev/null || log "(no start log)"
  log "--- latest IBC log ---"
  pct exec "$CTID" -- bash -c "ls -t $LOG_DIR/ibc-*.txt 2>/dev/null | head -1 | xargs tail -40" || log "(no ibc log)"
  log "--- gatewaystart.sh ---"
  pct exec "$CTID" -- ls -l /opt/ibc/gatewaystart.sh 2>/dev/null || log "(missing)"
  log "=== End diagnostics ==="
}

# Wait for the container itself to be running (handles host reboot)
log "Waiting for CT $CTID to be running..."
for i in {1..30}; do
  if pct status "$CTID" 2>/dev/null | grep -q running; then
    break
  fi
  sleep 2
done
if ! pct status "$CTID" 2>/dev/null | grep -q running; then
  log "ERROR: CT $CTID did not come up"
  exit 1
fi

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

log "Waiting up to ${MAX_WAIT_SECS}s for Gateway API on port 4002..."
ready=0
for ((i=1; i<=MAX_WAIT_SECS/2; i++)); do
  if pct exec "$CTID" -- ss -tlnp 2>/dev/null | grep -q ':4002'; then
    log "Gateway ready."
    ready=1
    break
  fi
  sleep 2
done
if (( ready == 0 )); then
  log "ERROR: Gateway did not become ready on port 4002"
  dump_diagnostics
  # Still try to clean up
  pct exec "$CTID" -- su - "$IBG_USER" -c 'pkill -f "ibcalpha.ibc.IbcGateway" || true; pkill -f "Xvfb :99" || true' || true
  exit 1
fi

log "Running price update..."
if ! pct exec "$CTID" -- /opt/trading/update_prices.py; then
  log "update_prices.py failed"
  # fall through to cleanup
fi

log "Stopping IB Gateway..."
pct exec "$CTID" -- su - "$IBG_USER" -c '
  pkill -f "ibcalpha.ibc.IbcGateway" || true
  pkill -f "Xvfb :99" || true
' || true

log "Refresh complete."
log "Latest IBC log:"
pct exec "$CTID" -- bash -c "ls -t $LOG_DIR/ibc-*.txt | head -1 | xargs tail -20" || true
