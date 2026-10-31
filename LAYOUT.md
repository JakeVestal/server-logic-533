# Trading Stack Layout

Snapshot of key paths for the 533 trading system (IB Gateway + price refresh).

## Host (Proxmox)
- Hostname: luffy
- Repo checkout (host-side scripts): `/opt/trading`
- Working dir when snapshot taken: `/root`

## Container 200 (IB Gateway)
- Hostname: fintech-533
- Unprivileged LXC
- Network: DHCP on vmbr0
- Rootfs: 16G on local-lvm

## Paths inside CT 200

### `/opt/trading`
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
- Host-side entry point: `/opt/trading/refresh_prices.sh`
  (copy of `server_files/refresh_prices.sh` from this repo)
- Deployed copy (inside CT 200): `/opt/trading/refresh_prices.sh`
- Price updater: `/opt/trading/update_prices.py` (inside CT 200)

## How to run
On the Proxmox host:
```bash
/opt/trading/refresh_prices.sh
```

## Notes
- Gateway API listens on port 4002 (paper) when running
- `refresh_prices.sh` starts Xvfb + IBC, waits for 4002, runs the updater, then stops the Gateway
