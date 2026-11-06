#!/usr/bin/env python3
"""
Headless LSEG seed for equity reference data and daily history.

Accepts up to 25 RICs per call. Returns (ref_df, hist_df).
Credentials come from arguments or LSEG_APP_KEY / LSEG_USERNAME / LSEG_PASSWORD.
"""

import os
from datetime import datetime, timedelta
from typing import Tuple

import pandas as pd
import lseg.data as ld
import pytz


def seed_equity_and_identifiers(
        rics: str | list[str],
        app_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        lookback_days: int = 365,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch reference and one-year daily historical data for one or more equity RICs.

    Parameters
    ----------
    rics : str or list of str
        Single RIC or list of RICs (maximum 25).
    app_key, username, password : str, optional
        LSEG credentials. If omitted, read from environment variables
        LSEG_APP_KEY, LSEG_USERNAME, LSEG_PASSWORD.
    lookback_days : int, default 365
        Number of calendar days of history to request.

    Returns
    -------
    ref_df : DataFrame
        Instrument reference data with clean column names.
    hist_df : DataFrame
        Daily OHLCV + volume/turnover/trades, date index, proper dtypes.

    Raises
    ------
    ValueError
        If more than 25 RICs are supplied or credentials are missing.
    """
    if isinstance(rics, str):
        rics = [rics]

    if len(rics) > 25:
        raise ValueError(f"Maximum 25 RICs allowed per call; received {len(rics)}")

    app_key = app_key or os.getenv("LSEG_APP_KEY")
    username = username or os.getenv("LSEG_USERNAME")
    password = password or os.getenv("LSEG_PASSWORD")

    if not all([app_key, username, password]):
        raise ValueError("Missing LSEG credentials")

    # --- Session ---
    session = ld.session.platform.Definition(
        app_key=app_key,
        grant=ld.session.platform.GrantPassword(username=username, password=password),
        signon_control=True,
    ).get_session()
    session.open()
    ld.session.set_default(session)
    print(f"Session opened for {len(rics)} RIC(s)")

    try:
        # --- Date range (exclude today if market still open) ---
        est = pytz.timezone("America/New_York")
        now_est = datetime.now(est)
        market_close = now_est.replace(hour=16, minute=0, second=0, microsecond=0)

        end_date = (
            (now_est - timedelta(days=1)).strftime("%Y-%m-%d")
            if now_est < market_close
            else now_est.strftime("%Y-%m-%d")
        )
        start_date = (now_est - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # --- Reference ---
        ref_fields = [
            "TR.CommonName",
            "TR.CompanyName",
            "TR.ExchangeName",
            "TR.PrimaryRIC",
            "TR.GICSSector",
            "TR.GICSIndustryGroup",
            "TR.GICSIndustry",
            "TR.TRBCIndustryGroup",
            "TR.HeadquartersCountry",
            "TR.OrganizationID",
        ]
        ref_rename = {
            "Company Common Name": "common_name",
            "Company Name": "company_name",
            "Exchange Name": "exchange_name",
            "Primary Issue RIC": "primary_ric",
            "GICS Sector Name": "gics_sector",
            "GICS Industry Group Name": "gics_industry_group",
            "GICS Industry Name": "gics_industry",
            "TRBC Industry Group Name": "trbc_industry_group",
            "Country of Headquarters": "headquarters_country",
            "Organization PermID": "organization_id",
        }

        ref_raw = ld.get_data(universe=rics, fields=ref_fields)
        ref_df = ref_raw.rename(columns={k: v for k, v in ref_rename.items() if k in ref_raw.columns})
        keep = ["Instrument"] + [v for v in ref_rename.values() if v in ref_df.columns]
        ref_df = ref_df[keep]
        for col in ref_df.columns:
            if col != "Instrument":
                ref_df[col] = ref_df[col].astype("string")
        print(f"Reference query successful ({len(ref_df)} rows, {len(ref_df.columns)} columns)")

        # --- Historical ---
        hist_fields = [
            "TR.OPENPRICE",
            "TR.HIGHPRICE",
            "TR.LOWPRICE",
            "TR.CLOSEPRICE",
            "TR.Volume",
            "TR.TSVWAP",
            "TR.TURNOVER",
            "TR.NUMBEROFTRADES",
            "TR.NUMBEROFBLOCKTRADES",
        ]
        hist_rename = {
            "Open Price": "open",
            "High Price": "high",
            "Low Price": "low",
            "Close Price": "close",
            "Volume": "volume",
            "TS VWAP": "ts_vwap",
            "VWAP": "ts_vwap",
            "Turnover": "turnover",
            "Number of Trades": "number_of_trades",
            "Number of Block Trades": "number_of_block_trades",
        }

        hist_raw = ld.get_data(
            universe=rics,
            fields=hist_fields,
            parameters={
                "SDate": start_date,
                "EDate": end_date,
                "Frq": "D",
                "Adjusted": "1",
            },
        )
        hist_df = hist_raw.rename(columns={k: v for k, v in hist_rename.items() if k in hist_raw.columns})

        if "Date" in hist_df.columns:
            hist_df["date"] = pd.to_datetime(hist_df["Date"]).dt.date
            hist_df = hist_df.drop(columns=["Date"])
        elif hist_df.index.name == "date" or (hasattr(hist_df.index, "date") is False and "date" not in hist_df.columns):
            # Fallback: if LSEG already put dates on the index
            if hist_df.index.name is not None or not isinstance(hist_df.index, pd.RangeIndex):
                hist_df = hist_df.reset_index()
                if "index" in hist_df.columns and "date" not in hist_df.columns:
                    hist_df = hist_df.rename(columns={"index": "date"})
        if "date" in hist_df.columns:
            hist_df["date"] = pd.to_datetime(hist_df["date"]).dt.date
            hist_df = hist_df.sort_values("date")
        else:
            raise RuntimeError("Historical data has no date column after processing")

        float_cols = ["open", "high", "low", "close", "ts_vwap", "turnover"]
        int_cols = ["volume", "number_of_trades", "number_of_block_trades"]
        for c in float_cols:
            if c in hist_df.columns:
                hist_df[c] = pd.to_numeric(hist_df[c], errors="coerce").astype("float64")
        for c in int_cols:
            if c in hist_df.columns:
                hist_df[c] = pd.to_numeric(hist_df[c], errors="coerce").astype("Int64")

        print(f"Historical query successful ({len(hist_df)} rows, {start_date} → {end_date})")
        return ref_df, hist_df

    finally:
        session.close()
        print("Session closed")
