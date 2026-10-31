# Setup Guide — 533 Trading Stack

How to stand up the IB Gateway + price-refresh system on a Proxmox host.
If the server is wiped, follow this to recreate what we built.

## Overview

- **Host**: Proxmox (hostname `luffy`)
- **Container**: LXC CT 200 (`fintech-533`) — unprivileged, runs IB Gateway via IBC
- **Repo**: `https://github.com/JakeVestal/server-logic-533` checked out at `/opt/server-logic-533`
- **Deploy**: GitHub Actions SSHs to the host on push to `main` (paths `server_files/**` or `host_files/**`)
- **Entry point**: `/opt/trading/refresh_prices.sh` on the host

## 1. Proxmox host prerequisites

- Proxmox VE installed
- Tailscale installed and joined (so GitHub Actions can reach the host)
- Git installed
- SSH key pair whose private key is stored in the GitHub secret `HOMELAB_SSH_KEY`
- The host is reachable at the IP/hostname stored in the GitHub secret `HOMELAB_HOST`

## 2. Create CT 200

```bash
pct create 200 local:vztmpl/debian-13-standard_*.tar.zst \
  --hostname fintech-533 \
  --rootfs local-lvm:16 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1
pct start 200
```

(Adjust the template name to whatever is available in `/var/lib/vz/template/cache`.)

## 3. Inside CT 200 — base packages and users

```bash
pct exec 200 -- bash -c '
  apt update
  apt install -y openjdk-17-jre-headless xvfb x11vnc python3 python3-venv python3-pip git ca-certificates
  useradd -m -s /bin/bash ibgateway || true
'
```

## 4. Install IBC + IB Gateway (inside CT 200)

Download and install IB Controller (IBC) and the IB Gateway under `/opt/ibc`.  
The exact install steps depend on the IBC release you use; the end state should be:

```
/opt/ibc/
  gatewaystart.sh
  config.ini          # IBC config (paper account, port 4002, etc.)
  IBC.jar
  ...
```

Gateway settings and logs live under the `ibgateway` user:

```
/home/ibgateway/
  Jts/
  ibc/logs/
```

The Gateway must be configured for **paper trading** and listen on **port 4002**.

## 5. Python environment inside CT 200

```bash
pct exec 200 -- bash -c '
  mkdir -p /opt/trading
  python3 -m venv /opt/trading/venv
  /opt/trading/venv/bin/pip install ibapi requests
'
```

Create the GitHub token file (secret, mode 600):

```bash
pct exec 200 -- bash -c '
  echo "YOUR_GITHUB_TOKEN" > /opt/trading/github_token
  chmod 600 /opt/trading/github_token
  chown root:root /opt/trading/github_token
'
```

## 6. Host repo checkout

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/JakeVestal/server-logic-533.git
chmod +x /opt/server-logic-533/host_files/*.sh
```

## 7. First deploy

```bash
cd /opt/server-logic-533
./host_files/deploy-server-logic.sh
```

This:
- copies `host_files/refresh_prices.sh` → `/opt/trading/refresh_prices.sh` (mode 755)
- tars `server_files/` into CT 200 `/opt/trading/`

## 8. GitHub Actions secrets

In the repo settings, set these secrets:

| Secret | Value |
|--------|-------|
| `TAILSCALE_AUTHKEY` | Tailscale auth key that can join the tailnet |
| `HOMELAB_HOST` | Tailscale IP or MagicDNS name of the Proxmox host |
| `HOMELAB_SSH_KEY` | Private key that can SSH to the host as root |

The workflow (`.github/workflows/deploy.yml`) will then deploy on every push to `main` that touches `server_files/**` or `host_files/**`.

## 9. Run the price refresh

```bash
/opt/trading/refresh_prices.sh
```

What it does:
1. Waits for CT 200 to be running
2. Starts Xvfb `:99` and IB Gateway (via IBC) inside the container
3. Waits up to 300s for port 4002
4. Runs `/opt/trading/update_prices.py` inside the container
5. Stops the Gateway and Xvfb

## 10. Cron (optional)

To run daily at 18:00:

```bash
echo '0 18 * * * /opt/trading/refresh_prices.sh >> /var/log/refresh_prices.log 2>&1' | crontab -
```

## File map

| Location | Purpose |
|----------|---------|
| `/opt/server-logic-533` | Git checkout of this repo |
| `/opt/trading/refresh_prices.sh` | Stable host entry point (installed by deploy) |
| `host_files/deploy-server-logic.sh` | Deploy script run by the workflow |
| `host_files/refresh_prices.sh` | Source for the host entry point |
| `server_files/update_prices.py` | Price updater (runs inside CT 200) |
| `server_files/subscribed_repos.txt` | Repos to update |
| CT 200 `/opt/trading/` | Deployed copies of `server_files/` + `github_token` + `venv` |
| CT 200 `/opt/ibc/` | IBC installation |
| CT 200 `/home/ibgateway/` | Gateway settings and logs |

## Notes

- The Gateway API port is **4002** (paper).
- `refresh_prices.sh` uses a virtual display (Xvfb). Connecting with TigerVNC will not show the Gateway unless you separately attach a VNC server to `:99`.
- The old `/root/deploy-server-logic.sh` is no longer used; the workflow runs the script from the repo checkout.
