#!/usr/bin/env bash
# Full price refresh: start IB Gateway via IBC, run update_prices.py, stop Gateway.
# Robust against cold starts / reboots.
set -euo pipefail

CTID=200
IBG_USER=ibgateway
LOG_DIR=/home/${IBG_USER}/ibc/logs
MAX_WAIT_SECS=300   # 5 minutes for Gateway to become ready

log() { echo "[$(date +'%H:%M:%S')] $*"; }

# ---------------------------------------------------------------------------
# Early exit on weekends and US market holidays (no Gateway start)
# ---------------------------------------------------------------------------
market_open_today() {
  # Runs inside CT200 using the trading venv (exchange_calendars)
  pct exec "$CTID" -- /opt/trading/venv/bin/python - << 'PY'
import sys
from datetime import date
try:
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XNYS")
    today = date.today()
    if cal.is_session(today):
        sys.exit(0)   # open
    else:
        sys.exit(1)   # closed
except ImportError:
    # Fallback: weekend-only check if the package is missing
    import datetime
    if datetime.date.today().weekday() >= 5:
        sys.exit(1)
    sys.exit(0)
PY
}

if ! market_open_today; then
  log "US markets closed today (weekend or holiday). Exiting without starting Gateway."
  exit 0
fi

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

# Kill leftover processes from a previous failed run
cleanup_gateway() {
  # Kill as root inside the container so we can reach any leftover processes
  pct exec "$CTID" -- bash -c '
    pkill -f "ibcalpha.ibc.IbcGateway" || true
    pkill -f "install4j.ibgateway.GWClient" || true
    pkill -f "Xvfb :99" || true
  ' || true
}

log "Clearing any leftover Gateway / Xvfb processes..."
cleanup_gateway
sleep 1

log "Starting IB Gateway (CT $CTID)..."
pct exec "$CTID" -- su - "$IBG_USER" -c '
  # Start Xvfb and wait until it is actually running
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

log "Waiting up to ${MAX_WAIT_SECS}s for Gateway API on port 4002..."
ready=0
for ((i=1; i<=MAX_WAIT_SECS/2; i++)); do
  if pct exec "$CTID" -- ss -tlnp 2>/dev/null | grep -q ':4002'; then
    log "Gateway ready."
    ready=1
    break
  fi
  # Progress every ~10s
  if (( i % 5 == 0 )); then
    elapsed=$((i * 2))
    log "  ... ${elapsed}s elapsed, still waiting"
    # Surface recent log lines that look like problems
    pct exec "$CTID" -- bash -c '
      latest=$(ls -t /home/ibgateway/ibc/logs/ibc-*.txt 2>/dev/null | head -1)
      if [ -n "$latest" ]; then
        tail -15 "$latest" | grep -iE "already logged|login failed|error|exception|conflict|another instance|cannot connect" || true
      fi
      if [ -f /tmp/ibg-start.log ]; then
        tail -5 /tmp/ibg-start.log | grep -iE "error|fail|exception" || true
      fi
    ' || true
  fi
  sleep 2
done
if (( ready == 0 )); then
  log "ERROR: Gateway did not become ready on port 4002"
  dump_diagnostics
  # Still try to clean up
  cleanup_gateway
  exit 1
fi

# Allow time for paper trading disclaimer dialog to be accepted
log "Waiting 15s for disclaimer dialogs to clear..."
sleep 15

log "Running price update..."
py_log=$(mktemp)
set +e
pct exec "$CTID" -- /opt/trading/venv/bin/python /opt/trading/update_prices.py >"$py_log" 2>&1
py_status=$?
set -e

# Per-repo detail now. The "=== Summary ===" block is held for the end.
if grep -q '^=== Summary ===' "$py_log"; then
  awk 'BEGIN{p=1} /^=== Summary ===/{exit} {print}' "$py_log"
else
  cat "$py_log"
fi

log "Stopping IB Gateway..."
cleanup_gateway
sleep 2

# Compact process list: pid, user, elapsed, command name. Not the Java classpath.
list_leftovers() {
  pct exec "$CTID" -- bash -c '
    ps -eo pid,user,etime,comm,args --no-headers 2>/dev/null \
      | grep -E "ibc|gateway|tws|java|Xvfb" \
      | grep -v grep \
      | awk "{print \$1, \$2, \$3, \$4}" \
      || true
  ' || true
}

log "=================================================="
log "LEFTOVERS"
log "=================================================="
leftovers=$(list_leftovers)
if [[ -n "${leftovers//[[:space:]]/}" ]]; then
  log "Found:"
  echo "$leftovers" | sed 's/^/  /'
  log "Killing leftovers..."
  pct exec "$CTID" -- bash -c '
    pids=$(ps -eo pid,args --no-headers 2>/dev/null \
      | grep -E "ibc|gateway|tws|java|Xvfb" \
      | grep -v grep \
      | awk "{print \$1}")
    if [[ -n "$pids" ]]; then
      kill -9 $pids || true
    fi
  ' || true
  sleep 1
  leftovers=$(list_leftovers)
  if [[ -n "${leftovers//[[:space:]]/}" ]]; then
    log "WARNING: still present after kill:"
    echo "$leftovers" | sed 's/^/  /'
  else
    log "Leftovers cleared."
  fi
else
  log "No leftover processes."
fi

log "=================================================="
log "IBC LOG (last 15 lines)"
log "=================================================="
pct exec "$CTID" -- bash -c "ls -t $LOG_DIR/ibc-*.txt 2>/dev/null | head -1 | xargs tail -15" || log "(no ibc log)"

echo
log "=================================================="
log "SUMMARY"
log "=================================================="
if grep -q '^=== Summary ===' "$py_log"; then
  awk '/^=== Summary ===/,0' "$py_log"
else
  log "(python printed no summary)"
fi
echo
log "price_run.json:"
pct exec "$CTID" -- cat /opt/trading/price_run.json 2>/dev/null || log "(no status file)"
echo
if (( py_status == 0 )); then
  log "Result: SUCCESS"
else
  log "Result: FAILED"
fi
rm -f "$py_log"
