# Trading Stack Layout

Snapshot of key paths for the 533 trading system (IB Gateway + price refresh).
Based on observed state as of 2026-10-31.

## Host (Proxmox)
- Hostname: luffy
- Working dir when snapshot taken: `/root`
- `/opt/trading` on the host: **does not exist** (snapshot showed missing)

## Container 200 (IB Gateway)
- Hostname: fintech-533
- Unprivileged LXC
- Network: DHCP on vmbr0
- Rootfs: 16G on local-lvm

## Paths inside CT 200

### `/opt/trading` (inside container)
```
refresh_prices.sh      # full start-IBG → update → stop script
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
- Source of truth: `server_files/refresh_prices.sh` in this repo
- Deployed copy (inside CT 200 only): `/opt/trading/refresh_prices.sh`
- Price updater: `/opt/trading/update_prices.py` (inside CT 200)

## How to run
`refresh_prices.sh` uses `pct exec`, so it must be run on the Proxmox host.
There is currently no host-side copy. Either:
1. Check the repo out on the host and run `server_files/refresh_prices.sh`, or
2. Copy the script to a fixed host path (e.g. `/usr/local/bin/refresh_prices.sh`) and run that.

## Notes
- Gateway API listens on port 4002 (paper) when running
- `refresh_prices.sh` starts Xvfb + IBC, waits for 4002, runs the updater, then stops the Gateway
