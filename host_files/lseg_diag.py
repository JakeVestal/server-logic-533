#!/usr/bin/env python3
"""
Diagnostic: what does LSEG actually return for a single RIC
around today, and what does the volume field look like?
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import lseg.data as ld
import pytz

RIC = "SNOW.N"

# Credentials from the same files the seed uses
os.environ["LSEG_APP_KEY"] = Path("/opt/trading/lseg_app_key").read_text().strip()
os.environ["LSEG_USERNAME"] = Path("/opt/trading/lseg_username").read_text().strip()
os.environ["LSEG_PASSWORD"] = Path("/opt/trading/lseg_password").read_text().strip()

est = pytz.timezone("America/New_York")
now = datetime.now(est)
print(f"Now (ET): {now}")
print(f"Market close today: {now.replace(hour=16, minute=0, second=0, microsecond=0)}")

session = ld.session.platform.Definition(
    app_key=os.environ["LSEG_APP_KEY"],
    grant=ld.session.platform.GrantPassword(
        username=os.environ["LSEG_USERNAME"],
        password=os.environ["LSEG_PASSWORD"],
    ),
    signon_control=True,
).get_session()
session.open()
ld.session.set_default(session)
print("Session open")

try:
    # Ask for the last 5 calendar days explicitly
    end = now.strftime("%Y-%m-%d")
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"Requesting {RIC}  {start} → {end}")

    df = ld.get_data(
        universe=[RIC],
        fields=[
            "TR.PriceClose.date",
            "TR.OPENPRICE",
            "TR.HIGHPRICE",
            "TR.LOWPRICE",
            "TR.CLOSEPRICE",
            "TR.Volume",
            "TR.TSVWAP",
            "TR.TURNOVER",
            "TR.NUMBEROFTRADES",
        ],
        parameters={
            "SDate": start,
            "EDate": end,
            "Frq": "D",
            "Adjusted": "1",
        },
    )
    print("\n=== Raw columns ===")
    print(list(df.columns))
    print("\n=== Raw rows ===")
    print(df.to_string())
    print("\n=== dtypes ===")
    print(df.dtypes)
finally:
    session.close()
    print("\nSession closed")
