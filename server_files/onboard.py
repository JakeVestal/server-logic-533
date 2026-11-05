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
    """Stop IB Gateway and sweep leftovers. Safe to call multiple times."""
    print("Stopping IB Gateway session...")
    for pat in ["ibcalpha.ibc.IbcGateway", "install4j.ibgateway.GWClient", "Xvfb :99"]:
        try:
            _run(["pkill", "-f", pat], check=False)
        except Exception as exc:
            print(f"  (pkill {pat} warning: {exc})")
    time.sleep(1)
    try:
        subprocess.run(
            "pids=$(ps -eo pid,args --no-headers 2>/dev/null | "
            "grep -E 'ibc|gateway|tws|java|Xvfb' | grep -v grep | awk '{print $1}'); "
            'if [ -n "$pids" ]; then kill -9 $pids || true; fi',
            shell=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:
        print(f"  (leftover sweep warning: {exc})")
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


def check_existing(symbol: str) -> tuple[int | None, int]:
    """Return (instrument_id, daily_bar_count) if the equity already exists, else (None, 0)."""
    with open_robin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id FROM instruments WHERE sec_type = 'STK' AND symbol = %s",
                (symbol,),
            )
            row = cur.fetchone()
            if not row:
                return None, 0
            instrument_id = row[0]
            cur.execute(
                "SELECT COUNT(*) FROM daily_bars WHERE instrument_id = %s",
                (instrument_id,),
            )
            bar_count = cur.fetchone()[0]
            return instrument_id, bar_count


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
            "primary_exchange": d.contract.primaryExchange or None,
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


def _bar_date(bar) -> "date":
    d = bar.date
    if hasattr(d, "date"):
        d = d.date()
    return d


def seed_equity_data(conn, instrument_id: int, conid: int, symbol: str, years: int = 1) -> None:
    """
    Fetch 1 year of equity seed data from IB and write to Robin.
    - TRADES -> daily_bars (OHLCV + vwap + trade_count)
    - ADJUSTED_LAST -> daily_bars.adj_close / adj_factor
    - HISTORICAL_VOLATILITY -> equity_volatilities.historical_vol_30d
    - OPTION_IMPLIED_VOLATILITY -> equity_volatilities.implied_vol_30d
    - ReportSnapshot fundamentals -> instrument_details (shares_out, market_cap, beta, dividend_ttm)
    Nulls stay null. Failures on optional series are logged and skipped.
    """
    from ib_insync import IB, Contract
    import xml.etree.ElementTree as ET
    from datetime import date

    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        contract = Contract(conId=conid, exchange="SMART", secType="STK", currency="USD")
        ib.qualifyContracts(contract)
        duration = f"{years} Y"

        def fetch(what: str):
            print(f"  {symbol}: requesting {what} ({duration})")
            return ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow=what,
                useRTH=True,
                formatDate=1,
            ) or []

        trades = fetch("TRADES")
        adjusted = fetch("ADJUSTED_LAST")
        hist_vol = fetch("HISTORICAL_VOLATILITY")
        impl_vol = fetch("OPTION_IMPLIED_VOLATILITY")

        # Map adjusted close by date
        adj_by_date = {}
        for bar in adjusted:
            try:
                adj_by_date[_bar_date(bar)] = float(bar.close)
            except (TypeError, ValueError):
                pass

        written = 0
        with conn.cursor() as cur:
            for bar in trades:
                try:
                    bd = _bar_date(bar)
                    close = float(bar.close)
                    adj_close = adj_by_date.get(bd)
                    adj_factor = (adj_close / close) if (adj_close is not None and close) else None
                    cur.execute("""
                        INSERT INTO daily_bars (
                            instrument_id, bar_date, open, high, low, close,
                            volume, open_interest, vendor, vwap, trade_count,
                            adj_close, adj_factor
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'ib', %s, %s, %s, %s)
                        ON CONFLICT (instrument_id, bar_date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            vwap = EXCLUDED.vwap,
                            trade_count = EXCLUDED.trade_count,
                            adj_close = EXCLUDED.adj_close,
                            adj_factor = EXCLUDED.adj_factor,
                            vendor = EXCLUDED.vendor
                    """, (
                        instrument_id, bd,
                        float(bar.open), float(bar.high), float(bar.low), close,
                        int(bar.volume) if bar.volume is not None else None,
                        float(bar.average) if bar.average else None,
                        int(bar.barCount) if bar.barCount else None,
                        adj_close, adj_factor,
                    ))
                    written += 1
                except Exception as exc:
                    print(f"  {symbol}: skip bar {getattr(bar, 'date', '?')}: {exc}")
        conn.commit()
        print(f"  {symbol}: {written} daily bars upserted")

        # Vols
        def upsert_vols(bars, column: str) -> int:
            n = 0
            with conn.cursor() as cur:
                for bar in bars:
                    try:
                        bd = _bar_date(bar)
                        val = float(bar.close)
                        cur.execute(f"""
                            INSERT INTO equity_volatilities (instrument_id, as_of_date, {column}, source)
                            VALUES (%s, %s, %s, 'ib')
                            ON CONFLICT (instrument_id, as_of_date) DO UPDATE SET
                                {column} = EXCLUDED.{column},
                                source = 'ib'
                        """, (instrument_id, bd, val))
                        n += 1
                    except Exception:
                        pass
            conn.commit()
            return n

        print(f"  {symbol}: {upsert_vols(hist_vol, 'historical_vol_30d')} historical vol rows")
        print(f"  {symbol}: {upsert_vols(impl_vol, 'implied_vol_30d')} implied vol rows")

        # Fundamentals snapshot (best effort)
        shares_out = market_cap = beta = dividend_ttm = None
        try:
            xml = ib.reqFundamentalData(contract, "ReportSnapshot")
            if xml:
                root = ET.fromstring(xml)
                # SharesOut
                so = root.find(".//SharesOut")
                if so is not None and so.text:
                    shares_out = int(float(so.text))
                # Ratios
                for ratio in root.findall(".//Ratio"):
                    name = ratio.get("FieldName") or ""
                    text = (ratio.text or "").strip()
                    if not text:
                        continue
                    try:
                        val = float(text)
                    except ValueError:
                        continue
                    if name == "MKTCAP":
                        market_cap = val
                    elif name in ("BETA", "ABETA"):
                        beta = val
                    elif name in ("ADIVSHR", "TTMDIV", "ADIV5YAVG"):
                        if dividend_ttm is None:
                            dividend_ttm = val
        except Exception as exc:
            print(f"  {symbol}: fundamentals unavailable ({exc})")

        if any(v is not None for v in (shares_out, market_cap, beta, dividend_ttm)):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE instrument_details SET
                        shares_out = COALESCE(%s, shares_out),
                        market_cap = COALESCE(%s, market_cap),
                        beta = COALESCE(%s, beta),
                        dividend_ttm = COALESCE(%s, dividend_ttm),
                        fundamentals_as_of = CURRENT_DATE,
                        updated_at = now()
                    WHERE instrument_id = %s
                """, (shares_out, market_cap, beta, dividend_ttm, instrument_id))
            conn.commit()
            print(f"  {symbol}: fundamentals written (shares_out={shares_out}, mktcap={market_cap}, beta={beta}, div_ttm={dividend_ttm})")
        else:
            print(f"  {symbol}: no fundamentals parsed")
    finally:
        ib.disconnect()


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
    Resolve, print card, require confirmation, then upsert.
    Returns instrument_id only after the user confirms.
    Raises on any failure or rejection.
    Nothing is written to Robin before confirmation.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol required")

    # Check for existing instrument before starting Gateway or writing
    instrument_id, bar_count = check_existing(symbol)
    if instrument_id is not None:
        print(f"{symbol} already exists (instrument_id={instrument_id}, {bar_count} daily bars).")
        print("Proceeding will update instrument details and refresh 1 year of equity data.")
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise RuntimeError(f"User declined to update existing {symbol}. Aborting.")

    gateway_start()
    try:
        details = fetch_ib_details(symbol)
        conid = details["conid"]

        # Preview only — no instrument_id yet
        print("\nResolved instrument (preview, not yet written):")
        print(f"  symbol:            {symbol}")
        print(f"  IB conid:          {conid}")
        print(f"  short_name:        {details.get('short_name') or '(none)'}")
        print(f"  full_name:         {details.get('full_name') or '(none)'}")
        print(f"  industry:          {details.get('industry') or '(none)'}")
        print(f"  sector:            {details.get('sector') or '(none)'}")
        print(f"  primary_exchange:  {details.get('primary_exchange') or '(none)'}")
        print(f"  country:           {details.get('country') or '(none)'}")
        print()

        if not confirm():
            raise RuntimeError("User rejected the resolved instrument. Aborting.")

        # Write only after explicit confirmation
        with open_robin() as conn:
            instrument_id = upsert_instrument(conn, symbol, details, conid)
            print(f"Confirmed and written. instrument_id = {instrument_id}")
            print(f"Seeding 1 year of equity data for {symbol}...")
            seed_equity_data(conn, instrument_id, conid, symbol, years=1)

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
