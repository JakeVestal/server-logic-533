#!/usr/bin/env bash
# Reusable IB Gateway session helpers for CT 200.
# Source this file, then call ibgateway_start / ibgateway_stop.
# Does not replace the inline logic in update_price_history.sh.

set -euo pipefail

CTID="${CTID:-200}"
IBG_USER="${IBG_USER:-ibgateway}"
LOG_DIR="/home/${IBG_USER}/ibc/logs"
MAX_WAIT_SECS="${MAX_WAIT_SECS:-300}"

ibgateway_cleanup() {
  pct exec "$CTID" -- bash -c '
    pkill -f "ibcalpha.ibc.IbcGateway" || true
    pkill -f "install4j.ibgateway.GWClient" || true
    pkill -f "Xvfb :99" || true
  ' || true
}

ibgateway_start() {
  echo "[$(date +'%H:%M:%S')] Clearing leftover Gateway / Xvfb processes..."
  ibgateway_cleanup
  sleep 1

  echo "[$(date +'%H:%M:%S')] Setting ExistingSessionDetectedAction=primary..."
  pct exec "$CTID" -- python3 - << 'PY'
from pathlib import Path
path = Path("/opt/ibc/config.ini")
if not path.is_file():
    print("WARNING: /opt/ibc/config.ini not found.")
    raise SystemExit(0)
lines = path.read_text().splitlines()
out = []
found = False
for line in lines:
    if line.split("=", 1)[0].strip() == "ExistingSessionDetectedAction":
        out.append("ExistingSessionDetectedAction=primary")
        found = True
    else:
        out.append(line)
if not found:
    out.append("ExistingSessionDetectedAction=primary")
path.write_text("\n".join(out) + "\n")
print("ExistingSessionDetectedAction=primary")
PY

  echo "[$(date +'%H:%M:%S')] Starting IB Gateway (CT $CTID)..."
  pct exec "$CTID" -- su - "$IBG_USER" -c '
    nohup Xvfb :99 -screen 0 1024x768x24 >/tmp/xvfb.log 2>&1 &
    for i in $(seq 1 10); do
      if pgrep -f "Xvfb :99" >/dev/null; then
        break
      fi
      sleep 0.5
    done
    if ! pgrep -f "Xvfb :99" >/dev/null; then
      echo "Xvfb failed to start" >> /tmp/ibg-start.log
      exit 1
    fi
    export DISPLAY=:99
    nohup /opt/ibc/gatewaystart.sh -inline >/tmp/ibg-start.log 2>&1 &
  '

  echo "[$(date +'%H:%M:%S')] Waiting up to ${MAX_WAIT_SECS}s for Gateway API on port 4002..."
  local ready=0
  for ((i=1; i<=MAX_WAIT_SECS/2; i++)); do
    if pct exec "$CTID" -- ss -tlnp 2>/dev/null | grep -q ':4002'; then
      echo "[$(date +'%H:%M:%S')] Gateway ready."
      ready=1
      break
    fi
    sleep 2
  done
  if (( ready == 0 )); then
    echo "[$(date +'%H:%M:%S')] ERROR: Gateway did not become ready on port 4002"
    ibgateway_cleanup
    return 1
  fi

  # Paper-trading disclaimer is accepted by IBC; give it time to clear
  echo "[$(date +'%H:%M:%S')] Waiting 15s for disclaimer dialogs to clear..."
  sleep 15
  echo "[$(date +'%H:%M:%S')] IB Gateway session ready."
}

ibgateway_stop() {
  echo "[$(date +'%H:%M:%S')] Stopping IB Gateway..."
  ibgateway_cleanup
  sleep 2
  # Sweep any leftovers
  pct exec "$CTID" -- bash -c '
    pids=$(ps -eo pid,args --no-headers 2>/dev/null \
      | grep -E "ibc|gateway|tws|java|Xvfb" \
      | grep -v grep \
