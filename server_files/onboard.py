#!/usr/bin/env python3
"""
Robin onboard entry point.

resolve_equity(symbol) resolves a ticker against IB Gateway, upserts the
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

import subprocess
import time
import socket


def _gateway_listening() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", IB_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _run(cmd, check=True):
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def gateway_start() -> None:
    """Start IB Gateway via IBC if it is not already listening. Blocks until ready."""
    if _gateway_listening():
        print("IB Gateway already listening on 4002; reusing.")
        return

    print("Starting IB Gateway session...")
    for pat in ["ibcalpha.ibc.IbcGateway", "install4j.ibgateway.GWClient", "Xvfb :99"]:
        _run(["pkill", "-f", pat], check=False)
    time.sleep(1)

    # Ensure ExistingSessionDetectedAction=primary
    subprocess.run([
        "python3", "-c",
        "from pathlib import Path\n"
        "p = Path('/opt/ibc/config.ini')\n"
        "if p.is_file():\n"
        "    lines = p.read_text().splitlines()\n"
        "    out = []\n"
        "    found = False\n"
        "    for line in lines:\n"
        "        if line.split('=', 1)[0].strip() == 'ExistingSessionDetectedAction':\n"
        "            out.append('ExistingSessionDetectedAction=primary')\n"
        "            found = True\n"
        "        else:\n"
        "            out.append(line)\n"
        "    if not found:\n"
        "        out.append('ExistingSessionDetectedAction=primary')\n"
        "    p.write_text('\\n'.join(out) + '\\n')\n"
    ], check=False)

    start_script = (
        "nohup Xvfb :99 -screen 0 1024x768x24 >/tmp/xvfb.log 2>&1 &\n"
        "for i in $(seq 1 10); do\n"
        "  if pgrep -f 'Xvfb :99' >/dev/null; then break; fi\n"
        "  sleep 0.5\n"
        "done\n"
        "if ! pgrep -f 'Xvfb :99' >/dev/null; then\n"
        "  echo 'Xvfb failed' >> /tmp/ibg-start.log\n"
        "  exit 1\n"
        "fi\n"
        "export DISPLAY=:99\n"
        "nohup /opt/ibc/gatewaystart.sh -inline >/tmp/ibg-start.log 2>&1 &\n"
    )
    _run(["su", "-", "ibgateway", "-c", start_script])

    print("Waiting for Gateway API on port 4002...")
    for i in range(150):
        if _gateway_listening():
            print("Gateway port 4002 is open.")
            break
        if i % 10 == 0 and i > 0:
            print(f"  ... still waiting ({i * 2}s)")
        time.sleep(2)
    else:
        raise RuntimeError("IB Gateway did not become ready on port 4002")

    print("Waiting 15s for paper-trading disclaimer to clear...")
    time.sleep(15)
    print("IB Gateway session ready.")


def gateway_stop() -> None:
    """Stop IB Gateway and sweep leftovers."""
    print("Stopping IB Gateway session...")
    for pat in ["ibcalpha.ibc.IbcGateway", "install4j.ibgateway.GWClient", "Xvfb :99"]:
        _run(["pkill", "-f", pat], check=False)
    time.sleep(2)
    subprocess.run(
        "pids=$(ps -eo pid,args --no-headers 2>/dev/null | "
        "grep -E 'ibc|gateway|tws|java|Xvfb' | grep -v grep | awk '{print $1}'); "
        'if [ -n "$pids" ]; then kill -9 $pids || true; fi',
        shell=True,
        check=False,
    )
    print("IB Gateway stopped.")



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


def fetch_ib_details(symbol: str) -> dict:
    """
    Resolve symbol via IB Gateway (clientId 2).
    Returns dict with: conid, short_name, full_name, industry, sector,
    primary_exchange, country. Nulls stay null; never invent values.
    """
    from ib_insync import IB, Stock
    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        contract = Stock(symbol, "SMART", "USD")
        details_list = ib.reqContractDetails(contract)
        if not details_list:
            raise RuntimeError(f"IB returned no ContractDetails for {symbol}")
        d = details_list[0]
        return {
            "conid": d.contract.conId,
            "short_name": d.longName or None,
            "full_name": d.longName or None,
            "industry": d.industry or None,
            "sector": d.category or None,
            "primary_exchange": d.primaryExchange or d.contract.primaryExchange or None,
            "country": None,  # IB ContractDetails does not reliably supply country
        }
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

        # Vendor id (IB only)
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

    gateway_start()
    try:
        details = fetch_ib_details(symbol)
        conid = details["conid"]

        with open_robin() as conn:
            instrument_id = upsert_instrument(conn, symbol, details, conid)

        print_card(symbol, details, conid, instrument_id)
        if not confirm():
            raise RuntimeError("User rejected the resolved instrument. Aborting.")

        return instrument_id
    finally:
        gateway_stop()


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
