#!/usr/bin/env python3
"""
Fetch price_history.json from each subscribed repo,
update tracked contracts via IB Gateway,
and push the updated file back.

Bars are written only to the student GitHub repos.
This job does not touch Robin.
A short result is written to
/opt/trading/price_run.json for the dashboard.

Supports per-repo tokens via /opt/trading/student_repos.json.
Falls back to the legacy single-token + subscribed_repos.txt path
if that file is absent.
"""

import json
import os
import sys
import base64
import requests
from datetime import datetime, timedelta, timezone
from ib_insync import IB, Contract

STUDENT_REPOS_FILE = "/opt/trading/student_repos.json"
LEGACY_TOKEN_FILE = "/opt/trading/github_token"
LEGACY_REPOS_FILE = "/opt/trading/subscribed_repos.txt"
PRICE_RUN_FILE = "/opt/trading/price_run.json"

IB_HOST = "127.0.0.1"
IB_PORT = 4002
CLIENT_ID = 1
BAR_SIZE = "1 day"


# Seed ConIDs used when a student repo has no price_history.json yet.
# One is chosen at random to confirm two-way connectivity.
SEED_CONIDS = [
    ("AAPL",  265598,     "APPLE INC"),
    ("NVDA",  4815747,    "NVIDIA CORPORATION"),
    ("MSFT",  272093,     "MICROSOFT CORPORATION"),
    ("GOOGL", 208813720,  "ALPHABET INC"),
    ("SPY",   756733,     "SPDR S&P 500 ETF TRUST"),
    ("AMZN",  3691937,    "AMAZON.COM INC"),
]


def owner_repo(url):
    parts = url.strip().rstrip("/").split("/")
    return parts[-2], parts[-1].replace(".git", "")


def load_targets():
    """
    Return a list of (owner, repo, token) tuples.
    Prefers student_repos.json; falls back to legacy files.
    """
    targets = []

    try:
        with open(STUDENT_REPOS_FILE) as f:
            entries = json.load(f)
        for e in entries:
            repo_url = e.get("repo", "").strip()
            token = e.get("token", "").strip()
            if not repo_url or not token:
                continue
            owner, repo = owner_repo(repo_url)
            targets.append((owner, repo, token))
        if targets:
            print(f"Loaded {len(targets)} repos from {STUDENT_REPOS_FILE}")
            return targets
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        print(f"WARNING: {STUDENT_REPOS_FILE} is not valid JSON: {exc}")

    # Legacy fallback
    try:
        token = open(LEGACY_TOKEN_FILE).read().strip()
    except FileNotFoundError:
        print("ERROR: no student_repos.json and no github_token")
        return []

    try:
        with open(LEGACY_REPOS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    owner, repo = owner_repo(line)
                    targets.append((owner, repo, token))
    except FileNotFoundError:
        print(f"ERROR: {LEGACY_REPOS_FILE} not found")
        return []

    print(f"Loaded {len(targets)} repos from legacy files")
    return targets


def gh_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def get_file(owner, repo, path, token):
    r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=gh_headers(token),
    )
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]


def put_file(owner, repo, path, content, sha, message, token):
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha is not None:
        payload["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers=gh_headers(token),
        json=payload,
    )
    r.raise_for_status()


def parse_expiry(raw):
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%Y%m%d", "%Y%m"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


LOOKBACK_DAYS = 30


def stored_dates(history):
    found = set()
    for key in history:
        try:
            found.add(datetime.strptime(key, "%Y-%m-%d").date())
        except (TypeError, ValueError):
            continue
    return found


_calendar_warned = False


def nyse_sessions(start, end):
    """NYSE sessions in the range, or weekdays if the calendar cannot be loaded."""
    global _calendar_warned
    if start > end:
        return []
    try:
        import exchange_calendars as xcals
        index = xcals.get_calendar("XNYS").sessions_in_range(start, end)
    except Exception as exc:
        if not _calendar_warned:
            print(f"  calendar unavailable ({exc}); weekday check only")
            _calendar_warned = True
        days = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        return days
    out = []
    for stamp in index:
        out.append(stamp.date() if hasattr(stamp, "date") else stamp)
    return out


def request_start(history, today):
    """First date to ask IB for. None when nothing in the recent window is missing.

    A failed night leaves the previous session as the newest bar, so the next
    run starts the day after that and covers the whole gap. A hole underneath
    a newer bar is included too, as long as it is inside the lookback.
    """
    if not history:
        return today - timedelta(days=30)
    stored = stored_dates(history)
    if not stored:
        return today - timedelta(days=30)
    last = max(stored)
    first = min(stored)
    window_start = max(first, today - timedelta(days=LOOKBACK_DAYS))
    missing = [day for day in nyse_sessions(window_start, today) if day not in stored]
    start = last + timedelta(days=1)
    if missing:
        start = min(start, min(missing))
    if start > today:
        return None
    # A 1-day daily request often comes back empty. Overlap two extra days.
    return min(start, today - timedelta(days=2))


def write_status(status):
    status["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status["ok"] = bool(status["github_ok"] and not status["error"])
    tmp = PRICE_RUN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f, indent=2)
        f.write("\n")
    os.replace(tmp, PRICE_RUN_FILE)


def main():
    status = {
        "finished_at": None,
        "ok": False,
        "github_ok": True,
        "repos_seen": 0,
        "repos_pushed": 0,
        "error": None,
    }
    errors = []
    ib = None

    try:
        targets = load_targets()
        status["repos_seen"] = len(targets)
        if not targets:
            errors.append("No repos to process")
        else:
            ib = IB()
            ib.connect(IB_HOST, IB_PORT, clientId=CLIENT_ID)

            updated_repos = []
            for owner, repo, token in targets:
                print(f"Processing {owner}/{repo}")
                sha = None
                try:
                    data, sha = get_file(owner, repo, "price_history.json", token)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        import random
                        symbol, conid, name = random.choice(SEED_CONIDS)
                        print(f"  no price_history.json — seeding with {symbol} ({conid}, {name})")
                        data = {
                            str(conid): {
                                "tracked": True,
                                "name": name,
                                "price_history": {},
                            }
                        }
                    else:
                        print(f"  ERROR reading price_history.json: {exc}")
                        status["github_ok"] = False
                        errors.append(f"{owner}/{repo}: read failed")
                        continue
                except Exception as exc:
                    print(f"  ERROR reading price_history.json: {exc}")
                    status["github_ok"] = False
                    errors.append(f"{owner}/{repo}: read failed")
                    continue

                changed = False
                for conid, info in data.items():
                    if not info.get("tracked"):
                        continue

                    contract = Contract(conId=int(conid))
                    ib.qualifyContracts(contract)

                    history = info.get("price_history", {})
                    if not isinstance(history, dict):
                        history = {}
                        info["price_history"] = history
                    end = datetime.now()
                    today = end.date()
                    before = json.dumps(history, sort_keys=True)
                    try:
                        start = request_start(history, today)
                        if start is None:
                            print(f"  {conid}: up to date")
                        else:
                            span = (today - start).days + 1
                            if span > 365:
                                print(f"  {conid}: gap is {span} days; requesting the latest 365")
                                span = 365
                            print(f"  {conid}: requesting {span} day(s) ending {today}")
                            bars = ib.reqHistoricalData(
                                contract,
                                endDateTime=end,
                                durationStr=f"{span} D",
                                barSizeSetting=BAR_SIZE,
                                whatToShow="TRADES",
                                useRTH=True,
                                formatDate=1,
                            )
                            for bar in bars:
                                date_str = bar.date.strftime("%Y-%m-%d")
                                history[date_str] = {
                                    "open": bar.open,
                                    "high": bar.high,
                                    "low": bar.low,
                                    "close": bar.close,
                                    "volume": bar.volume,
                                }
                            info["price_history"] = history
                            if json.dumps(history, sort_keys=True) != before:
                                changed = True
                    except Exception as exc:
                        status["github_ok"] = False
                        errors.append(f"{owner}/{repo} {conid}: price request failed")
                        print(f"  ERROR requesting {conid}: {exc}")

                if not changed:
                    print("  no GitHub update needed")
                    continue

                updated = json.dumps(data, indent=2)
                try:
                    put_file(
                        owner, repo, "price_history.json", updated, sha,
                        f"Update price history {datetime.now():%Y-%m-%d}",
                        token,
                    )
                    print("  pushed updated price_history.json")
                    assets = []
                    for cid, info in data.items():
                        nm = info.get("name", "")
                        assets.append(f"{cid} ({nm})" if nm else cid)
                    updated_repos.append((owner, repo, assets))
                    status["repos_pushed"] += 1
                except Exception as exc:
                    status["github_ok"] = False
                    errors.append(f"{owner}/{repo}: push failed")
                    print(f"  ERROR pushing: {exc}")

            print()
            print("=== Summary ===")
            if not updated_repos:
                print("No repos updated on GitHub")
            else:
                for owner, repo, conids in updated_repos:
                    print(f"  {owner}/{repo}: {', '.join(conids)}")
            print(f"Total: {status['repos_pushed']} repo(s) pushed")
    except Exception as exc:
        errors.append(str(exc))
        print(f"ERROR: {exc}")
    finally:
        if ib is not None:
            try:
                ib.disconnect()
            except Exception:
                pass
        if errors:
            status["error"] = "; ".join(errors)[:500]
        try:
            write_status(status)
            print(f"Wrote {PRICE_RUN_FILE}")
        except Exception as exc:
            print(f"ERROR writing {PRICE_RUN_FILE}: {exc}")
            status["ok"] = False
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
