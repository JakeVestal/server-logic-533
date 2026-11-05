# Trading stack layout

Where things are. How to rebuild and how a market afternoon runs is [SETUP.md](SETUP.md) and [docs/setup.html](docs/setup.html). How a change gets into the repo is [PATCHES.txt](PATCHES.txt).

## Host (Luffy)

- Proxmox host. GitHub Actions reaches it over Tailscale, as root.
- Repo checkout: `/opt/server-logic-533`. Actions resets this checkout to `origin/main` on deploy.
- Stable host scripts, installed by deploy: `/opt/trading`
- Dispatch token, not in git: `/opt/trading/status_dispatch.token` (mode 600)
- Afternoon log: `/var/log/update-price-history.log`
- Cron is not in git. The line is in SETUP.md.

## Container 200 (Sanji)

- Unprivileged LXC, hostname `sanji`, on `vmbr0`. Nesting is on.
- Runs the price program, IB Gateway through IBC, and Xvfb.

### `/opt/trading` inside CT 200

| Path | What it is |
|---|---|
| `update_prices.py` | Deployed copy of `server_files/update_prices.py`. Daily bars, student repos, and the Robin upsert. |
| `student_repos.json` | Live subscription list. Mode 600. Not in git. |
| `robin_writer.password` | Password for the Robin writer. Mode 600. Not in git. |
| `price_run.json` | Last run summary. Not published. |
| `venv/` | Python virtualenv. Packages used by the job: `ib_insync`, `requests`, `psycopg[binary]`, `exchange_calendars`. |
| `github_token` | Legacy single token. Used only if `student_repos.json` is missing. Not the live path. |
| `subscribed_repos.txt` | Legacy repo list for that same fallback. A copy is in git at `server_files/subscribed_repos.txt`. |

### `/opt/ibc`

IB Controller. `gatewaystart.sh` starts Gateway. The paper login and API settings are in the IBC config on this container. They are not in git. Gateway listens on port 4002 when it is running.

### `/home/ibgateway`

Gateway settings, `Jts/`, and IBC logs. The user is `ibgateway`.

## Container 201 (Robin)

- Postgres database `robin`.
- Sanji connects with `ROBIN_HOST` and `ROBIN_PORT` in `server_files/update_prices.py`, user `robin_writer`.
- `robin_writer` can SELECT, INSERT, and UPDATE.
- `student_ro` can SELECT. It has no login password yet.
- Schema record: `robin/schema.sql`. Apply once, by hand, with `/opt/trading/apply_robin_schema.sh`. Deploy does not apply it.
- Tables today: `assets` (one IB contract, primary key `conid`) and `price_bars` (one OHLCV row per `conid`, `bar_size`, `bar_date`). `bar_size` is `1 day`. No IV or Greeks columns.
- The apply script drops those two tables when they are empty, and refuses when `price_bars` has rows unless `--force` is passed.

## Repo

| Path | What it is |
|---|---|
| `server_files/update_prices.py` | Price program. Deploy copies `server_files/` into CT 200 `/opt/trading/`. |
| `server_files/subscribed_repos.txt` | Legacy fallback list. The live list is `student_repos.json` on CT 200. |
| `host_files/update_price_history.sh` | Afternoon job. Installed to `/opt/trading/update_price_history.sh`. |
| `host_files/deploy-server-logic.sh` | What the deploy workflow runs after it updates the checkout. |
| `host_files/apply_robin_schema.sh` | Applies `robin/schema.sql`. |
| `host_files/publish_status.sh` | Asks GitHub to run the Luffy status workflow. |
| `host_files/dashboard_status.sh` | Builds the dashboard JSON. Run on Luffy by that workflow. |
| `host_files/add_repo.sh` | Add one student repo and PAT. |
| `host_files/update_pat.sh` | Replace one student PAT. |
| `host_files/view_repos.sh` | List subscribed URLs with tokens masked. |
| `host_files/remove_repo.sh` | Remove one URL. |
| `host_files/delete_repo.sh` | Remove every URL containing a search string. |
| `robin/schema.sql` | Database record. |
| `docs/index.html` | Dashboard. |
| `docs/order.html` | Student spec for `positions.json` and `open_orders.json`. Not executed yet. |
| `docs/status.json` | Written by the Luffy status workflow. Do not edit it by hand. |
| `docs/setup.html` | Same recreation record as SETUP.md. |
| `docs/site.js` | Nav bar. |
| `docs/.nojekyll` | Pages serves the files as they are. |
| `.github/workflows/deploy.yml` | Deploy to Luffy. |
| `.github/workflows/status.yml` | Luffy status. SSH action is `appleboy/ssh-action@v1.2.5`. |
| `scripts/apply-latest-patch.sh` | Applies the next patch from `~/Downloads`. See PATCHES.txt. |
| `patch-record.txt` | One applied patch filename per line. |

## Not in git

`student_repos.json`, `robin_writer.password`, `github_token`, `status_dispatch.token`, the venv, the IBC config, and the cron line.
