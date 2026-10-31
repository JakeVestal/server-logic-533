#!/usr/bin/env bash
# Deploy host_files and server_files after the repo has been updated.
# Called by the GitHub Actions workflow after it does the git reset.

set -euo pipefail

REPO_DIR="/opt/server-logic-533"
CTID=200

cd "$REPO_DIR"

# Host-side script (stable cron path)
mkdir -p /opt/trading
install -m 755 host_files/refresh_prices.sh /opt/trading/refresh_prices.sh

# Container files
pct exec "$CTID" -- mkdir -p /opt/trading
tar -C server_files -cf - . | pct exec "$CTID" -- tar -C /opt/trading -xf -

echo "Deployed $(date)"
echo "  host:  /opt/trading/refresh_prices.sh"
echo "  ct200: /opt/trading/ (from server_files/)"
