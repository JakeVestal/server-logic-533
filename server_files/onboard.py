#!/usr/bin/env python3
"""
Robin onboard entry point.

resolve_equity(symbol) resolves a ticker against LSEG and IB, upserts the
instrument and details, prints the card, and requires explicit confirmation
before returning the instrument_id.

Later stages (seed, admit, etc.) will be added here.
"""

import sys
from datetime import date

# Robin connection constants match the course job
ROBIN_HOST = "192.168.1.202"
ROBIN_PORT = 5432
ROBIN_DB = "robin"
ROBIN_USER = "robin_writer"
ROBIN_PASSWORD_FILE = "/opt/trading/robin_writer.password"

# IB Gateway (must not be held by the course job)
IB_HOST = "127.0.0.1"
IB_PORT = 4002
IB_CLIENT_ID = 2  # different from course job clientId=1


def open_robin():
    password = open(ROBIN_PASSWORD_FILE).read().strip()
    if not password:
        raise RuntimeError(f"{ROBIN_PASSWORD_FILE} is empty")
    import psycopg
    return psycopg.connect(
        host=ROBIN_HOST,
        port=ROBIN_PORT,
        dbname=ROBIN_DB,
        user=ROBIN_USER,
        password=password,
        connect_timeout=10,
        application_name="robin-onboard",
    )


def fetch_lseg_details(symbol: str) -> dict:
    """
    Placeholder for LSEG lookup.
    Must return a dict with at least:
      ric, short_name, full_name, industry, sector, primary_exchange, country
    Nulls are allowed; never invent values.
    Raise if the lookup cannot be performed.
    """
    # TODO: wire real LSEG / lseg-data call here.
    # Example fields previously agreed: TR.CommonName, TR.TRBCIndustry, etc.
    raise NotImplementedError(
        "LSEG lookup not yet wired. Implement fetch_lseg_details before use."
    )


def fetch_ib_conid(symbol: str) -> int:
    """Resolve symbol to IB conid via Gateway. Uses clientId 2."""
    from ib_insync import IB, Stock
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        contract = Stock(symbol, "SMART", "USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"IB could not qualify {symbol}")
        return qualified[0].conId
    finally:
        ib.disconnect()


def upsert_instrument(conn, symbol: str, details: dict, conid: int) -> int:
    """Upsert instruments, vendor_ids, and instrument_details. Returns instrument_id."""
    with conn.cursor() as cur:
        # Equity row
        cur.execute("""
            INSERT INTO instruments (sec_type, symbol, currency, exchange)
            VALUES ('STK', %s, 'USD', %s)
            ON CONFLICT DO NOTHING
            RETURNING instrument_id
        """, (symbol, details.get("primary_exchange")))
        row = cur.fetchone()
        if row:
            instrument_id = row[0]
        else:
            cur.execute(
                "SELECT instrument_id FROM instruments WHERE sec_type = 'STK' AND symbol = %s",
                (symbol,),
            )
            instrument_id = cur.fetchone()[0]

        # Vendor ids
        if details.get("ric"):
            cur.execute("""
                INSERT INTO vendor_ids (instrument_id, vendor, vendor_id)
                VALUES (%s, 'lseg', %s)
                ON CONFLICT (vendor, vendor_id) DO NOTHING
            """, (instrument_id, details["ric"]))
        cur.execute("""
            INSERT INTO vendor_ids (instrument_id, vendor, vendor_id)
            VALUES (%s, 'ib', %s)
            ON CONFLICT (vendor, vendor_id) DO NOTHING
        """, (instrument_id, str(conid)))

        # Details (nulls stay null)
        cur.execute("""
            INSERT INTO instrument_details (
                instrument_id, short_name, full_name, industry, sector,
                primary_exchange, country
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instrument_id) DO UPDATE SET
                short_name = EXCLUDED.short_name,
                full_name = EXCLUDED.full_name,
                industry = EXCLUDED.industry,
                sector = EXCLUDED.sector,
                primary_exchange = EXCLUDED.primary_exchange,
                country = EXCLUDED.country,
                updated_at = now()
        """, (
            instrument_id,
            details.get("short_name"),
            details.get("full_name"),
            details.get("industry"),
            details.get("sector"),
            details.get("primary_exchange"),
            details.get("country"),
        ))
    conn.commit()
    return instrument_id


def print_card(symbol: str, details: dict, conid: int, instrument_id: int):
    print("\nResolved instrument:")
    print(f"  symbol:            {symbol}")
    print(f"  instrument_id:     {instrument_id}")
    print(f"  IB conid:          {conid}")
    print(f"  LSEG RIC:          {details.get('ric') or '(none)'}")
    print(f"  short_name:        {details.get('short_name') or '(none)'}")
    print(f"  full_name:         {details.get('full_name') or '(none)'}")
    print(f"  industry:          {details.get('industry') or '(none)'}")
    print(f"  sector:            {details.get('sector') or '(none)'}")
    print(f"  primary_exchange:  {details.get('primary_exchange') or '(none)'}")
    print(f"  country:           {details.get('country') or '(none)'}")
    print()


def confirm() -> bool:
    answer = input("Confirm this is the correct instrument? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def resolve_equity(symbol: str) -> int:
    """
    Resolve, upsert, print, and require confirmation.
    Returns instrument_id only after the user confirms.
    Raises on any failure or rejection.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol required")

    details = fetch_lseg_details(symbol)
    conid = fetch_ib_conid(symbol)

    with open_robin() as conn:
        instrument_id = upsert_instrument(conn, symbol, details, conid)

    print_card(symbol, details, conid, instrument_id)
    if not confirm():
        raise RuntimeError("User rejected the resolved instrument. Aborting.")

    return instrument_id


def main():
    if len(sys.argv) != 2:
        print("Usage: onboard.py SYMBOL", file=sys.stderr)
        sys.exit(2)
    symbol = sys.argv[1]
    try:
        iid = resolve_equity(symbol)
        print(f"Confirmed. instrument_id = {iid}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
