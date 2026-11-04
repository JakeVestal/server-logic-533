#!/usr/bin/env bash
# Deploy host_files and server_files after the repo has been updated.
# Called by the GitHub Actions workflow after it does the git reset.

set -euo pipefail

REPO_DIR="/opt/server-logic-533"
CTID=200

cd "$REPO_DIR"

# Host-side script (stable cron path)
mkdir -p /opt/trading
install -m 755 host_files/update_price_history.sh /opt/trading/update_price_history.sh
install -m 755 host_files/view_repos.sh     /opt/trading/view_repos.sh
install -m 755 host_files/add_repo.sh       /opt/trading/add_repo.sh
install -m 755 host_files/delete_repo.sh    /opt/trading/delete_repo.sh
install -m 755 host_files/apply_robin_schema.sh /opt/trading/apply_robin_schema.sh

# Container files
pct exec "$CTID" -- mkdir -p /opt/trading
tar -C server_files -cf - . | pct exec "$CTID" -- tar -C /opt/trading -xf -

echo "Deployed $(date)"
echo "  host:  /opt/trading/update_price_history.sh"
echo "  ct200: /opt/trading/ (from server_files/)"
echo "  robin schema is NOT applied by deploy. Run /opt/trading/apply_robin_schema.sh once."
