#!/usr/bin/env python3
"""
Load LSEG seed CSVs from /opt/trading/data_dump into Robin.
Processes identifiers-seed-*.csv and equity-seed-*.csv.
Moves processed files to data_dump/processed/.
"""

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

DUMP_DIR = Path("/opt/trading/data_dump")
PROCESSED = DUMP_DIR / "processed"
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
        application_name="lseg-dump-loader",
    )


def upsert_identifiers(conn, df: pd.DataFrame) -> int:
    n = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            ric = str(row.get("Instrument", "")).strip()
            if not ric:
                continue
            # Equity instrument (symbol = RIC for now; refine later)
            cur.execute("""
                INSERT INTO instruments (sec_type, symbol, currency)
                VALUES ('STK', %s, 'USD')
                ON CONFLICT DO NOTHING
                RETURNING instrument_id
            """, (ric,))
            res = cur.fetchone()
            if res:
                iid = res[0]
            else:
                cur.execute("SELECT instrument_id FROM instruments WHERE sec_type='STK' AND symbol=%s", (ric,))
                iid = cur.fetchone()[0]
            # vendor id
            cur.execute("""
                INSERT INTO vendor_ids (instrument_id, vendor, vendor_id)
                VALUES (%s, 'lseg', %s)
                ON CONFLICT (vendor, vendor_id) DO NOTHING
            """, (iid, ric))
            # details
            cur.execute("""
                INSERT INTO instrument_details (
                    instrument_id, short_name, full_name, industry, sector,
                    primary_exchange, country, gics_industry_group,
                    trbc_industry_group, organization_id, primary_ric
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (instrument_id) DO UPDATE SET
                    short_name = EXCLUDED.short_name,
                    full_name = EXCLUDED.full_name,
                    industry = EXCLUDED.industry,
                    sector = EXCLUDED.sector,
                    primary_exchange = EXCLUDED.primary_exchange,
                    country = EXCLUDED.country,
                    gics_industry_group = EXCLUDED.gics_industry_group,
                    trbc_industry_group = EXCLUDED.trbc_industry_group,
                    organization_id = EXCLUDED.organization_id,
                    primary_ric = EXCLUDED.primary_ric,
                    updated_at = now()
            """, (
                iid,
                row.get("common_name"),
                row.get("company_name"),
                row.get("gics_industry"),
                row.get("gics_sector"),
                row.get("exchange_name"),
                row.get("headquarters_country"),
                row.get("gics_industry_group"),
                row.get("trbc_industry_group"),
                str(row.get("organization_id")) if pd.notna(row.get("organization_id")) else None,
                row.get("primary_ric"),
            ))
            n += 1
    conn.commit()
    return n


def upsert_bars(conn, df: pd.DataFrame) -> int:
    if "date" not in df.columns:
        raise RuntimeError("equity CSV missing date column")
    n = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            ric = str(row.get("Instrument", "")).strip()
            if not ric or pd.isna(row.get("date")):
                continue
            cur.execute("""
                SELECT i.instrument_id FROM instruments i
                JOIN vendor_ids v ON v.instrument_id = i.instrument_id
                WHERE v.vendor='lseg' AND v.vendor_id=%s
            """, (ric,))
            res = cur.fetchone()
            if res:
                iid = res[0]
            else:
                # Minimal row so the bar can land. Details filled later if identifiers arrive.
                cur.execute("SELECT instrument_id FROM instruments WHERE sec_type='STK' AND symbol=%s", (ric,))
                res = cur.fetchone()
                if res:
                    iid = res[0]
                else:
                    cur.execute("""
                        INSERT INTO instruments (sec_type, symbol, currency)
                        VALUES ('STK', %s, 'USD')
                        RETURNING instrument_id
                    """, (ric,))
                    iid = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO vendor_ids (instrument_id, vendor, vendor_id)
                    VALUES (%s, 'lseg', %s)
                    ON CONFLICT (vendor, vendor_id) DO NOTHING
                """, (iid, ric))
            cur.execute("""
                INSERT INTO daily_bars (
                    instrument_id, bar_date, open, high, low, close,
                    volume, vwap, trade_count, turnover, number_of_block_trades, vendor
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'lseg')
                ON CONFLICT (instrument_id, bar_date) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    vwap = EXCLUDED.vwap,
                    trade_count = EXCLUDED.trade_count,
                    turnover = EXCLUDED.turnover,
                    number_of_block_trades = EXCLUDED.number_of_block_trades,
                    vendor = EXCLUDED.vendor
            """, (
                iid, row["date"],
                row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                int(row["volume"]) if pd.notna(row.get("volume")) else None,
                row.get("ts_vwap"),
                int(row["number_of_trades"]) if pd.notna(row.get("number_of_trades")) else None,
                row.get("turnover"),
                int(row["number_of_block_trades"]) if pd.notna(row.get("number_of_block_trades")) else None,
            ))
            n += 1
    conn.commit()
    return n


def main():
    PROCESSED.mkdir(exist_ok=True)
    files = sorted(DUMP_DIR.glob("*-seed-*.csv"))
    if not files:
        print("No seed CSVs found")
        return 0
    with get_conn() as conn:
        for f in files:
            print(f"Processing {f.name}")
            df = pd.read_csv(f)
            if f.name.startswith("identifiers-seed-"):
                n = upsert_identifiers(conn, df)
                print(f"  {n} identifiers")
            elif f.name.startswith("equity-seed-"):
                n = upsert_bars(conn, df)
                print(f"  {n} bars")
            else:
                continue
            # Move only if every row in the file was written
            if n == len(df):
                f.rename(PROCESSED / f.name)
            else:
                print(f"  {f.name}: wrote {n}/{len(df)} rows — leaving in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
