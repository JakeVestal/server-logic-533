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
install -m 755 host_files/update_pat.sh     /opt/trading/update_pat.sh
install -m 755 host_files/apply_robin_schema.sh /opt/trading/apply_robin_schema.sh
install -m 755 host_files/publish_status.sh    /opt/trading/publish_status.sh

# The price script in git does not call the publisher, so a 4pm run would
# leave the website stale. install replaces the script on every deploy,
# which drops a previous append, so add the call back once.
if ! grep -q '/opt/trading/publish_status.sh' /opt/trading/update_price_history.sh; then
  cat >> /opt/trading/update_price_history.sh << 'EOF'

# Refresh the public dashboard. Does not start Gateway.
# A missing token or a GitHub error must not fail the price run.
if [[ -x /opt/trading/publish_status.sh ]]; then
  /opt/trading/publish_status.sh || echo "[$(date +'%H:%M:%S')] Dashboard refresh was not requested."
fi
EOF
fi

# Container files
pct exec "$CTID" -- mkdir -p /opt/trading
tar -C server_files -cf - . | pct exec "$CTID" -- tar -C /opt/trading -xf -
pct exec "$CTID" -- /opt/trading/venv/bin/pip install --disable-pip-version-check 'psycopg[binary]'

echo "Deployed $(date)"
echo "  host:  /opt/trading/update_price_history.sh"
echo "  ct200: /opt/trading/ (from server_files/)"
echo "  robin schema is NOT applied by deploy. Run /opt/trading/apply_robin_schema.sh once."
