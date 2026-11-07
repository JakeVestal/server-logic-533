#!/usr/bin/env python3
"""
Options seeder driver.
Reads options_shopping_list, prioritizes near-expiry + near-ATM,
fetches 5-day history in batches, writes options-seed-*.csv.
Backs off 15 min if the LSEG session is in use.
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import lseg.data as ld
import pytz

DUMP_DIR = Path("/opt/trading/data_dump")
ROBIN_HOST = "192.168.1.202"
ROBIN_PORT = 5432
ROBIN_DB = "robin"
ROBIN_USER = "robin_writer"
ROBIN_PASSWORD_FILE = "/opt/trading/robin_writer.password"
LOOKBACK_DAYS = 5
BATCH_CONTRACTS = 40          # conservative; 5 days * ~15 fields
MAX_ROWS = 3000
SESSION_RETRY_SECS = 15 * 60

MONTH_CODES = {
    1: ("A", "M"), 2: ("B", "N"), 3: ("C", "O"), 4: ("D", "P"),
    5: ("E", "Q"), 6: ("F", "R"), 7: ("G", "S"), 8: ("H", "T"),
    9: ("I", "U"), 10: ("J", "V"), 11: ("K", "W"), 12: ("L", "X"),
}

FIELDS = [
    "TR.CLOSEPRICE.DATE",
    "TR.OPENPRICE", "TR.HIGHPRICE", "TR.LOWPRICE", "TR.CLOSEPRICE",
    "TR.ACCUMULATEDVOLUME",
    "TR.IMPLIEDVOLATILITY", "TR.OPENINTEREST",
    "TR.DELTA", "TR.GAMMA", "TR.THETA", "TR.VEGA", "TR.RHO",
    "TR.BIDPRICE", "TR.ASKPRICE", "TR.MIDPRICE",
]


def construct_opra_ric(underlying_ric, expiry, strike, right):
    root = underlying_ric.split(".")[0]
    exp = pd.to_datetime(expiry)
    letter = MONTH_CODES[exp.month][0 if right.upper().startswith("C") else 1]
    if strike >= 1000:
        letter = letter.lower()
    if strike < 1000:
        strike_str = f"{int(round(strike * 100)):05d}"
    else:
        strike_str = f"{int(round(strike * 10)):05d}"
        if len(strike_str) > 5:
            strike_str = f"{int(round(strike)):05d}"[:5]
    return f"{root}{letter}{exp.day:02d}{exp.year % 100:02d}{strike_str}.U"


def get_conn():
    password = Path(ROBIN_PASSWORD_FILE).read_text().strip()
    return psycopg.connect(
        host=ROBIN_HOST, port=ROBIN_PORT, dbname=ROBIN_DB,
        user=ROBIN_USER, password=password, connect_timeout=10,
        application_name="options-seeder",
    )


def next_batch(conn):
    """Return prioritized untracked contracts with last close."""
    sql = """
    WITH last_close AS (
      SELECT v.vendor_id AS underlying, b.close
      FROM vendor_ids v
      JOIN daily_bars b ON b.instrument_id = v.instrument_id
      WHERE v.vendor = 'lseg'
        AND b.bar_date = (
          SELECT MAX(bar_date) FROM daily_bars b2
          WHERE b2.instrument_id = v.instrument_id
        )
    )
    SELECT s.underlying, s.expiry, s.strike,
           s.p_untracked, s.c_untracked, lc.close AS last_close
    FROM options_shopping_list s
    LEFT JOIN last_close lc ON lc.underlying = s.underlying
    WHERE s.p_untracked OR s.c_untracked
    ORDER BY
      s.expiry ASC,
      CASE WHEN lc.close IS NULL OR lc.close = 0 THEN 999
           ELSE ABS(s.strike - lc.close) / lc.close END ASC,
      s.underlying
    LIMIT {BATCH_CONTRACTS}
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    # Decode any bytes columns
    clean = []
    for row in rows:
        clean.append(tuple(
            v.decode() if isinstance(v, (bytes, bytearray)) else v
            for v in row
        ))
    return pd.DataFrame(clean, columns=cols)


def open_session():
    app_key = Path("/opt/trading/lseg_app_key").read_text().strip()
    username = Path("/opt/trading/lseg_username").read_text().strip()
    password = Path("/opt/trading/lseg_password").read_text().strip()
    session = ld.session.platform.Definition(
        app_key=app_key,
        grant=ld.session.platform.GrantPassword(username=username, password=password),
        signon_control=True,
    ).get_session()
    session.open()
    ld.session.set_default(session)
    return session


def main():
    DUMP_DIR.mkdir(exist_ok=True)
    print(f"[{datetime.now():%H:%M:%S}] Options seeder starting")
    while True:
        try:
            with get_conn() as conn:
                batch = next_batch(conn)
            if batch.empty:
                print(f"[{datetime.now():%H:%M:%S}] Shopping list empty — sleeping 30 min")
                time.sleep(30 * 60)
                continue

            # Build RICs for untracked sides
            rows = []
            for _, r in batch.iterrows():
                if r["c_untracked"]:
                    rows.append({**r, "right": "C",
                                 "ric": construct_opra_ric(r["underlying"], r["expiry"], r["strike"], "C")})
                if r["p_untracked"]:
                    rows.append({**r, "right": "P",
                                 "ric": construct_opra_ric(r["underlying"], r["expiry"], r["strike"], "P")})
            if not rows:
                time.sleep(60)
                continue
            work = pd.DataFrame(rows)
            print(f"[{datetime.now():%H:%M:%S}] Batch of {len(work)} contract sides")

            # Session with backoff
            session = None
            for attempt in range(1, 5):
                try:
                    session = open_session()
                    break
                except Exception as exc:
                    print(f"  session attempt {attempt} failed: {exc}")
                    if attempt == 4:
                        print("  giving up this cycle")
                        break
                    print(f"  sleeping {SESSION_RETRY_SECS//60} min")
                    time.sleep(SESSION_RETRY_SECS)
            if session is None:
                continue

            try:
                est = pytz.timezone("America/New_York")
                end = (datetime.now(est) - timedelta(days=1)).strftime("%Y-%m-%d")
                start = (datetime.now(est) - timedelta(days=LOOKBACK_DAYS + 2)).strftime("%Y-%m-%d")
                print(f"  fetching {start} → {end}")
                hist = ld.get_data(
                    universe=work["ric"].tolist(),
                    fields=FIELDS,
                    parameters={"SDate": start, "EDate": end, "Frq": "D"},
                )
                # Write CSV
                n = len(list(DUMP_DIR.glob("options-seed-*.csv"))) + 1
                out = DUMP_DIR / f"options-seed-{n}.csv"
                hist.to_csv(out, index=False)
                print(f"  wrote {out.name} ({len(hist)} rows)")
            finally:
                session.close()

            time.sleep(3)
        except KeyboardInterrupt:
            print("Stopping")
            break
        except Exception as exc:
            print(f"ERROR: {exc}")
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main() or 0)
