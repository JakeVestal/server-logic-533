#!/usr/bin/env python3
"""
Nami: Saturday shopping-list manager.
Uses ld.discovery.search to find options, then applies the ±30% / expiry rules
and upserts into options_shopping_list.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import lseg.data as ld

sys.path.insert(0, str(Path(__file__).parent))
from shopping_list_rules import filter_chain

ROBIN_HOST = "192.168.1.202"
ROBIN_PORT = 5432
ROBIN_DB = "robin"
ROBIN_USER = "robin_writer"
ROBIN_PASSWORD_FILE = "/opt/trading/robin_writer.password"


def get_conn():
    password = Path(ROBIN_PASSWORD_FILE).read_text().strip()
    return psycopg.connect(
        host=ROBIN_HOST, port=ROBIN_PORT, dbname=ROBIN_DB,
        user=ROBIN_USER, password=password, connect_timeout=10,
        application_name="nami",
    )


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


def tracked_underlyings(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT v.vendor_id
            FROM vendor_ids v
            JOIN instruments i ON i.instrument_id = v.instrument_id
            WHERE v.vendor = 'lseg' AND i.sec_type = 'STK'
        """)
        return [r[0] for r in cur.fetchall()]


def last_close(conn, underlying: str) -> float | None:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT b.close
            FROM vendor_ids v
            JOIN daily_bars b ON b.instrument_id = v.instrument_id
            WHERE v.vendor = 'lseg' AND v.vendor_id = %s::text
            ORDER BY b.bar_date DESC
            LIMIT 1
        """, (underlying,))
        row = cur.fetchone()
        return float(row[0]) if row else None


def discover_chain(underlying: str, today: date) -> list[dict]:
    """Return raw chain rows via discovery.search."""
    end = today + timedelta(days=800)
    filt = (
        f"SearchAllCategoryv2 eq 'Options' and "
        f"UnderlyingQuoteRIC eq '{underlying}' and "
        f"ExpiryDate ge {today.isoformat()} and "
        f"ExpiryDate le {end.isoformat()}"
    )
    df = ld.discovery.search(
        view=ld.discovery.Views.SEARCH_ALL,
        top=5000,
        filter=filt,
        select="ExpiryDate,StrikePrice,CallPutOption,RIC",
    )
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        try:
            rows.append({
                "underlying": underlying,
                "expiry": pd.to_datetime(r["ExpiryDate"]).date(),
                "strike": float(r["StrikePrice"]),
                "right": str(r.get("CallPutOption", "")),
                "ric": r.get("RIC"),
            })
        except Exception:
            continue
    return rows


def upsert_list(conn, rows: list[dict]):
    with conn.cursor() as cur:
        for r in rows:
            cur.execute("""
                INSERT INTO options_shopping_list (underlying, expiry, strike)
                VALUES (%s, %s, %s)
                ON CONFLICT (underlying, expiry, strike) DO NOTHING
            """, (r["underlying"], r["expiry"], r["strike"]))
    conn.commit()


def main():
    today = date.today()
    print(f"[{today}] Nami starting")
    session = open_session()
    try:
        with get_conn() as conn:
            underlyings = tracked_underlyings(conn)
            print(f"  {len(underlyings)} tracked underlyings")
            for u in underlyings:
                lc = last_close(conn, u)
                if lc is None:
                    print(f"  {u}: no last close — skip")
                    continue
                raw = discover_chain(u, today)
                if not raw:
                    print(f"  {u}: no chain returned")
                    continue
                filtered = filter_chain(raw, lc, today)
                upsert_list(conn, filtered)
                print(f"  {u}: {len(raw)} raw → {len(filtered)} on list (close={lc:.2f})")
            # Cleanup completed
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM options_shopping_list
                    WHERE p_untracked = FALSE AND c_untracked = FALSE
                """)
            conn.commit()
            print("  removed completed rows")
    finally:
        session.close()
    print("Nami done")


if __name__ == "__main__":
    sys.exit(main() or 0)
