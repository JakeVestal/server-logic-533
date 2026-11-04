# Trading Stack Layout

Snapshot of key paths for the 533 trading system (IB Gateway + price refresh).

## Host (Proxmox)
- Hostname: luffy
- Repo checkout: `/opt/server-logic-533`
- Stable host scripts: `/opt/trading`

## Container 200 (IB Gateway)
- Hostname: fintech-533
- Unprivileged LXC
- Network: DHCP on vmbr0
- Rootfs: 16G on local-lvm

## Paths inside CT 200

### `/opt/trading`
```
update_prices.py       # fetches history via IB API and pushes to GitHub
subscribed_repos.txt   # list of repos to update
github_token           # (secret, mode 600)
venv/                  # Python virtualenv
```

### `/opt/ibc`
IB Controller installation (IBC). Key files:
- `gatewaystart.sh` — starts IB Gateway
- `config.ini` — IBC configuration
- `IBC.jar`

### `/home/ibgateway`
- `Jts/` — Gateway settings / jts.ini / logs
- `ibc/` — IBC runtime logs
- User: `ibgateway`

## Important scripts

### Host
- Entry point (stable cron path): `/opt/trading/update_price_history.sh`
  Source: `host_files/update_price_history.sh` in this repo
- Deploy script: `host_files/deploy-server-logic.sh`
  (run by the GitHub Actions workflow after it updates the checkout)

### Container
- Price updater: `/opt/trading/update_prices.py`

## How to run
On the Proxmox host:
```bash
/opt/trading/update_price_history.sh
```

## Deploy flow
1. Push to `main` that touches `server_files/**` or `host_files/**`
2. GitHub Actions SSHs to the host
3. Workflow does `git fetch` + `git reset --hard origin/main` in `/opt/server-logic-533`
4. Workflow runs `./host_files/deploy-server-logic.sh`
5. Deploy script:
   - installs `host_files/update_price_history.sh` → `/opt/trading/update_price_history.sh`
   - tars `server_files/` into CT 200 `/opt/trading/`

## Notes
- Gateway API listens on port 4002 (paper) when running
- `update_price_history.sh` starts Xvfb + IBC, waits for 4002, runs the updater, then stops the Gateway
