#!/usr/bin/env python3
"""
Nami: Saturday shopping-list manager.

For each tracked underlying:
1. Use Chain to get option constituents.
2. Pull EXPIR_DATE and STRIKE_PRC.
3. Keep expiries ≤ 6 months, plus nearest ~1y and ~2y.
4. Keep strikes within ±30% of last close.
5. Upsert into options_shopping_list.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import lseg.data as ld

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
        out = []
        for r in cur.fetchall():
            v = r[0]
            out.append(v.decode() if isinstance(v, (bytes, bytearray)) else str(v))
        return out


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


def chain_ric(underlying: str) -> str:
    """OPRA chain RIC: 0#<ROOT>*.U"""
    root = underlying.split(".")[0]
    return f"0#{root}*.U"


def select_expiries(expiries: list[date], today: date) -> list[date]:
    expiries = sorted(set(e for e in expiries if e >= today))
    short = [e for e in expiries if e <= today + timedelta(days=183)]
    def nearest(days: int) -> date | None:
        target = today + timedelta(days=days)
        cands = [e for e in expiries if e > today]
        return min(cands, key=lambda e: abs((e - target).days)) if cands else None
    out = set(short)
    for d in (365, 730):
        n = nearest(d)
        if n:
            out.add(n)
    return sorted(out)


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
                cric = chain_ric(u)
                try:
                    constituents = ld.discovery.Chain(name=cric).constituents
                except Exception as exc:
                    print(f"  {u}: chain {cric} failed: {exc}")
                    continue
                if not constituents:
                    print(f"  {u}: empty chain")
                    continue
                # Pull expiry and strike in chunks so we see the full chain
                # without exceeding per-call row guidance.
                chunks = []
                step = 400
                for i in range(0, len(constituents), step):
                    part = ld.get_data(
                        universe=constituents[i:i+step],
                        fields=["EXPIR_DATE", "STRIKE_PRC"],
                    )
                    if part is not None and not part.empty:
                        chunks.append(part)
                if not chunks:
                    print(f"  {u}: no chain data")
                    continue
                df = pd.concat(chunks, ignore_index=True)
                df = df.dropna(subset=["EXPIR_DATE", "STRIKE_PRC"])
                df["expiry"] = pd.to_datetime(df["EXPIR_DATE"]).dt.date
                df["strike"] = pd.to_numeric(df["STRIKE_PRC"], errors="coerce")
                df = df.dropna(subset=["strike"])
                wanted = select_expiries(df["expiry"].tolist(), today)
                lo, hi = lc * 0.70, lc * 1.30
                keep = df[df["expiry"].isin(wanted) & df["strike"].between(lo, hi)]
                # Upsert unique (expiry, strike)
                pairs = keep[["expiry", "strike"]].drop_duplicates()
                with conn.cursor() as cur:
                    for _, r in pairs.iterrows():
                        cur.execute("""
                            INSERT INTO options_shopping_list (underlying, expiry, strike)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (underlying, expiry, strike) DO NOTHING
                        """, (u, r["expiry"], float(r["strike"])))
                conn.commit()
                print(f"  {u}: {len(pairs)} contracts (close={lc:.2f}, chain={cric})")
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
