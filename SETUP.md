# Setup — 533 trading system

How to stand this system back up, and how it runs. This is the same record as [docs/setup.html](docs/setup.html). Paths are in [LAYOUT.md](LAYOUT.md). How a change gets into the repo is [PATCHES.txt](PATCHES.txt).

This file names paths and secret names. It does not contain tokens, passwords, private keys, or Tailscale auth keys. Those stay on the host or in GitHub Actions secrets. Do not paste them into git, into this file, or into a commit.

## The pieces

| Piece | What it is |
|---|---|
| Luffy | The Proxmox host. GitHub Actions reaches it over Tailscale, as root, by SSH. The repo is checked out at `/opt/server-logic-533`. Stable operator scripts live in `/opt/trading`. |
| Sanji, CT 200 | Unprivileged LXC. Runs IB Gateway through IBC on a virtual display, fetches daily bars, writes `price_history.json` to each student repo, and upserts the same bars into Robin. |
| Robin, CT 201 | Postgres. Database name `robin`. One shared price table. Sanji is the writer. Students, later, get a read-only role. |
| This repo | `server_files/` is what runs inside Sanji. `host_files/` is what runs on Luffy. `docs/` is the public site. `robin/schema.sql` is the database record. |
| The site | GitHub Pages, from `docs/` on `main`. The dashboard reads `status.json`. The order menu is the student spec. Sanji does not resolve those orders yet. |

## What is on a clock

One cron job. No systemd timer, and neither GitHub workflow has a `schedule`. The line is not in git. On a host whose clock is America/New_York it is:

```
0 16 * * 1-5 /opt/trading/update_price_history.sh >> /var/log/update-price-history.log 2>&1
```

If the host clock is UTC, use 21:00 UTC while the US is on standard time and 20:00 UTC while it is on daylight time. The log path stays the same. The script puts `/usr/sbin` on `PATH` itself, because cron's path does not include `pct`.

These are not on a clock. They run because something else happened:

- Deploy to Luffy, on a push to `main` that touches `server_files/` or `host_files/`.
- Luffy status, at the end of a price run that gets that far, after a successful deploy, or from the Actions button. A weekend or holiday exit does not call it.
- Pages rebuilds when that workflow pushes `docs/status.json`.

## What happens on a market afternoon

The cron line above runs `/opt/trading/update_price_history.sh`.

1. The script asks `exchange_calendars` whether the NYSE (XNYS) is in session. Exit 1 means closed, and the script stops before Gateway starts. Any other failure is an error, not a holiday. If that package is missing, only Saturday and Sunday are skipped, so install it.
2. It waits until CT 200 is running, then clears leftover Gateway and Xvfb processes.
3. It sets `ExistingSessionDetectedAction=primary` in the IBC config on CT 200. Gateway then takes the IB session. A phone that is already logged in is disconnected.
4. As the `ibgateway` user, it starts `Xvfb :99` and `/opt/ibc/gatewaystart.sh`. Gateway is the paper account and listens on port `4002`. The wait is up to 300 seconds.
5. `/opt/trading/venv/bin/python /opt/trading/update_prices.py` runs inside CT 200. Client id is 1. Bar size is `1 day`.
6. For each entry in `/opt/trading/student_repos.json`, Sanji reads that repo's `price_history.json` with that repo's token. A missing file is seeded with one of the built-in contracts. For each contract it asks Gateway for missing NYSE sessions in the last 30 days, not only the days after the newest bar. The request overlaps two extra days, because a one-day daily request often comes back empty. A contract with nothing missing in that window is skipped. Changed files are pushed. The commit message starts with `Update price history`.
7. The same bars are upserted into Robin. The password is the contents of `/opt/trading/robin_writer.password` inside CT 200. The host and port are the `ROBIN_HOST` and `ROBIN_PORT` constants in `server_files/update_prices.py`.
8. A short result is written to `/opt/trading/price_run.json` inside CT 200. That file is not published.
9. Gateway and Xvfb are stopped. The script prints leftovers and the Python summary.
10. The installed price script calls `/opt/trading/publish_status.sh` at the end. A failure there does not fail the price run. That script asks GitHub to run the Luffy status workflow. It does not start Gateway.

There is a legacy path. If `student_repos.json` is missing, `update_prices.py` falls back to one token in `/opt/trading/github_token` and the list in `subscribed_repos.txt`. Do not use that path for a new setup. The live list is the JSON file. `server_files/subscribed_repos.txt` is still in git because the program still knows the fallback.

## How the dashboard mark is set

The Luffy status workflow SSHs to Luffy and runs `host_files/dashboard_status.sh` from the checkout. For each subscribed repo it does two GitHub calls with that student's token, and it never prints the token.

- It creates one git blob whose text is `luffy-dashboard-permission-check`. The same text is reused, so later checks do not pile up objects. This does not create a commit and does not show in the student's history. HTTP 200 or 201 means the token can write. Anything else is not connected. A read of the repo is not enough, because GitHub would report the student's own permission rather than the token's.
- It looks through commits on `price_history.json` for the newest message that starts with `Update price history`. That time is the Last server update column. A student commit does not count. Never means we have not pushed that file.

If GitHub says the rate limit is exhausted, the script exits before printing JSON. The workflow then does not commit, and the previous `status.json` stays. A rate limit must not turn every row into a red X.

The workflow writes `docs/status.json` and pushes it. Pages rebuilds. A green check is `connected: true`. A red X is false. A dash means this copy of the file was written before the check existed.

The workflow runs when any of these happen:

- Someone opens Actions → Luffy status → Run workflow.
- `/opt/trading/publish_status.sh` runs. The price job calls it at the end. Run it by hand after a PAT change.
- The Deploy to Luffy workflow succeeds.

`publish_status.sh` reads `/opt/trading/status_dispatch.token` on Luffy, not inside a container. That file is a fine-grained PAT for this one repository, permission Actions read and write, nothing else. It cannot read student repos. Create it with no expiration so a semester boundary does not silently stop the refresh. GitHub still revokes a token that goes unused for a year. The afternoon job uses it on market days.

```
umask 077
read -r -s -p "dispatch token: " T
printf '%s' "$T" > /opt/trading/status_dispatch.token
unset T
chmod 600 /opt/trading/status_dispatch.token
```

## Operator commands

Run these on Luffy as root. Deploy installs them to `/opt/trading`. The copies in `host_files/` are the source. `student_repos.json` stays mode 600 inside CT 200. None of these scripts print a full token. `view_repos.sh` and `update_pat.sh` print a mask: the first 7 characters, then `...`, then the last 4.

| Command | What it does |
|---|---|
| `add_repo.sh` | Asks for a repo URL and a PAT. Appends one object. Refuses a duplicate URL. |
| `update_pat.sh` | Asks for a username, repo name, or URL. Lists matches. You pick one. Then it reads a new PAT, replaces that one token, reads it back from disk, and prints it masked. A search that hits several repos does not change the others. No match means they are not subscribed: use `add_repo.sh`. |
| `view_repos.sh` | Prints the URLs with the tokens masked. |
| `remove_repo.sh` | Removes one entry whose URL matches exactly. |
| `delete_repo.sh` | Removes every entry whose URL contains the search string. Confirm only if that is what you mean. |
| `publish_status.sh` | Presses the Luffy status button. Run it after adding a repo or replacing a PAT. The new mark appears when that workflow finishes, not when this command returns. |
| `update_price_history.sh` | The afternoon job, and the way to run it by hand. Starts Gateway and takes the IB session. Do not run it just to refresh the dashboard. Use `publish_status.sh` for that. |
| `apply_robin_schema.sh` | Applies `robin/schema.sql` once. Deploy does not run it. Refuses if `price_bars` already has rows unless you pass `--force`. |

A student PAT is fine-grained, on that one repository, with Contents set to Read and write. The click-by-click version is the collapsed section on the dashboard. The URL they send is the green Code URL, not a `github.io` address. Store it with `add_repo.sh` or replace it with `update_pat.sh`.

The JSON on CT 200 looks like this. The token here is a placeholder.

```
[
  {
    "repo": "https://github.com/owner/repo",
    "token": "github_pat_..."
  }
]
```

## The two workflows

Deploy to Luffy runs on a push to `main` that touches `server_files/**` or `host_files/**`. It joins Tailscale, SSHs to Luffy, runs `git fetch` and `git reset --hard origin/main` in `/opt/server-logic-533`, then `host_files/deploy-server-logic.sh`.

Deploy does four things:

- Installs the host scripts into `/opt/trading` with mode 755.
- Appends the `publish_status.sh` call to the installed price script, because a fresh install would otherwise drop it. The append is skipped when the call is already there.
- Tars `server_files/` into CT 200 `/opt/trading/`. This overwrites the Python program. It does not delete `student_repos.json`, `robin_writer.password`, or the venv, because those are not in `server_files/`. Do not add them to git.
- Pip-installs `psycopg[binary]` into the CT 200 venv. It does not install the other Python packages, and it does not apply the Robin schema.

Luffy status checks out the repo, joins Tailscale, and SSHs. The SSH action is `appleboy/ssh-action@v1.2.5` with `capture_stdout: true`. Do not downgrade that action. The v1.0.3 used by Deploy does not capture stdout, and Deploy does not need it to. The probe output is cut between the `DASHBOARD_JSON` markers, written to `docs/status.json`, and pushed as `github-actions[bot]` when the file changed.

GitHub Actions secrets, set on this repo, values not written down here:

| Secret | What it is |
|---|---|
| `TAILSCALE_AUTHKEY` | A Tailscale auth key that can join the tailnet. The runner has no route to Luffy without it. |
| `HOMELAB_HOST` | Luffy's Tailscale address. Not a public DNS name. |
| `HOMELAB_SSH_KEY` | The private key whose public half is in Luffy's root `authorized_keys`. |

## Rebuild Luffy

1. Install Proxmox. Install Tailscale and join the tailnet. Install git.
2. Create an SSH key for GitHub Actions. Put the public key in `/root/.ssh/authorized_keys` on Luffy. Put the private key in the `HOMELAB_SSH_KEY` secret. Put Luffy's Tailscale address in `HOMELAB_HOST`. Put a Tailscale auth key in `TAILSCALE_AUTHKEY`.
3. Clone `https://github.com/JakeVestal/server-logic-533.git` to `/opt/server-logic-533`. The Actions user must be able to `git fetch` it.
4. In the GitHub repo, set Pages to deploy from branch `main`, folder `/docs`. The repo contains `docs/.nojekyll`.
5. Create the dispatch token file shown above.
6. Install the cron line from "What is on a clock". Confirm the host timezone before you pick 16:00 versus 20:00 or 21:00 UTC.

## Rebuild Sanji, CT 200

Unprivileged Debian LXC, hostname `sanji`, on Luffy's `vmbr0`, with enough disk for the Gateway and a Python venv. Nesting is required because Gateway and Xvfb run inside the container.

```
pct exec 200 -- bash -c '
  apt update
  apt install -y openjdk-17-jre-headless xvfb python3 python3-venv python3-pip git ca-certificates
  useradd -m -s /bin/bash ibgateway || true
  mkdir -p /opt/trading
  python3 -m venv /opt/trading/venv
  /opt/trading/venv/bin/pip install ib_insync requests "psycopg[binary]" exchange_calendars
'
```

Install IBC and the IB Gateway under `/opt/ibc` so that `/opt/ibc/gatewaystart.sh` exists. The paper username, password, and API settings live in the IBC config on that container. They are not in git. The API port is 4002. Logs and Jts settings live under `/home/ibgateway/`.

Create the Robin password file inside the container, mode 600, owner root. Type it. Do not put it in the shell command, or it lands in history.

```
umask 077
read -r -s -p "robin_writer password: " P
printf '%s\n' "$P" > /tmp/robin_writer.password
unset P
pct push 200 /tmp/robin_writer.password /opt/trading/robin_writer.password
rm -f /tmp/robin_writer.password
pct exec 200 -- chmod 600 /opt/trading/robin_writer.password
```

Then add students with `/opt/trading/add_repo.sh` after the first deploy has installed it. That creates `student_repos.json`.

## Rebuild Robin, CT 201

1. Unprivileged LXC with Postgres. Create a database named `robin`.
2. Give CT 200 a route to CT 201's Postgres port. Put that address and port in `ROBIN_HOST` and `ROBIN_PORT` in `server_files/update_prices.py`, then deploy.
3. From Luffy, after the repo is at `/opt/server-logic-533`, run `/opt/trading/apply_robin_schema.sh` once. It applies `robin/schema.sql` and prompts for the `robin_writer` password. Use the same password as the file on CT 200.
4. `student_ro` can SELECT. `robin_writer` can SELECT, INSERT, and UPDATE. Neither password belongs in git. `student_ro` has no login password yet. The schema drops `price_bars` and `assets`. The apply script refuses when `price_bars` has rows.

Tables today: `assets` is one IB contract, keyed by conid. `price_bars` is one daily bar per contract and session date. Sanji writes `bar_size` as `1 day`. There are no IV or Greeks columns.

## What must not be published

| Thing | Where it lives |
|---|---|
| Student PATs | CT 200, `/opt/trading/student_repos.json`, mode 600. One token can write one student repo. |
| Dispatch PAT | Luffy, `/opt/trading/status_dispatch.token`, mode 600. Can only start a workflow on this repo. |
| Robin password | The role password in Postgres, and the same text in CT 200 `/opt/trading/robin_writer.password`. |
| IB login | IBC config inside CT 200. Paper account. |
| SSH private key and Tailscale auth key | GitHub Actions secrets only. |
