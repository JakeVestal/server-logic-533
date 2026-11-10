#!/usr/bin/env python3
"""
Minimal LSEG connection test for GitHub Actions.

Opens a platform session with credentials from the environment, fetches a short
OHLC history for one instrument, and writes a simple interactive Plotly chart
to docs/ so the site can display it.
"""

import os
import sys

import lseg.data as ld
import pandas as pd
import plotly.graph_objects as go


def open_lseg_session() -> None:
    app_key = os.environ.get("LSEG_APP_KEY")
    username = os.environ.get("LSEG_USERNAME")
    password = os.environ.get("LSEG_PASSWORD")
    if not all([app_key, username, password]):
        sys.exit("Missing LSEG_APP_KEY, LSEG_USERNAME, or LSEG_PASSWORD")

    session = ld.session.platform.Definition(
        app_key=app_key,
        grant=ld.session.platform.GrantPassword(
            username=username,
            password=password,
        ),
        signon_control=True,
    ).get_session()
    session.open()
    ld.session.set_default(session)
    print("LSEG platform session opened")


def fetch_simple_ohlc(ric: str = "AAPL.O", count: int = 60) -> pd.DataFrame:
    print(f"Fetching {count} daily bars for {ric}")
    df = ld.get_history(
        universe=ric,
        fields=["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1", "ACVOL_UNS"],
        interval="1D",
        count=count,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No history returned for {ric}")
    print(f"Received {len(df)} rows")
    print(df.tail())
    return df


def make_chart(df: pd.DataFrame, ric: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["OPEN_PRC"],
            high=df["HIGH_1"],
            low=df["LOW_1"],
            close=df["TRDPRC_1"],
            name=ric,
        )
    )
    fig.update_layout(
        title=f"{ric} daily OHLC (LSEG connection test)",
        xaxis_title="Date",
        yaxis_title="Price",
        height=500,
        xaxis_rangeslider_visible=False,
    )
    return fig


def main() -> None:
    ric = os.environ.get("OI_UNDERLYING_RIC", "AAPL.O")
    open_lseg_session()
    df = fetch_simple_ohlc(ric)
    fig = make_chart(df, ric)
    out = "docs/lseg-test.html"
    fig.write_html(out, include_plotlyjs="cdn", full_html=True)
    print(f"Wrote {out}")
    # also drop a tiny CSV so we have a data artifact
    df.to_csv("docs/lseg-test.csv")
    print("Wrote docs/lseg-test.csv")


if __name__ == "__main__":
    main()
