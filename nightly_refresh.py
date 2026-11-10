#!/usr/bin/env python3
"""
Generate Open Interest cluster plots for the nearest AAPL expiry.

Uses LSEG discovery search to find real option contracts, fetches recent
open interest with TR.OPENINTEREST, and writes two interactive Plotly charts
to docs/ so GitHub Pages can display them.
"""

import os
import sys
from datetime import datetime, timedelta

import lseg.data as ld
import pandas as pd
import plotly.graph_objects as go


def open_lseg_session() -> None:
    app_key = os.environ.get("LSEG_APP_KEY")
    username = os.environ.get("LSEG_USERNAME")
    password = os.environ.get("LSEG_PASSWORD")
    if not all([app_key, username, password]):
        raise RuntimeError("Missing LSEG_APP_KEY, LSEG_USERNAME, or LSEG_PASSWORD")

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


def main() -> None:
    open_lseg_session()

    print("Searching options for AAPL.O...")
    raw = ld.discovery.search(
        view=ld.discovery.Views.SEARCH_ALL,
        top=500,
        filter="SearchAllCategoryv2 eq 'Options' and UnderlyingQuoteRIC eq 'AAPL.O'",
        select="RIC,StrikePrice,ExpiryDate,CallPutOption",
    )
    df = raw.dropna(subset=["RIC", "StrikePrice", "ExpiryDate"]).copy()
    df = df[~df["RIC"].str.startswith("0#")]
    df["ExpiryDate"] = pd.to_datetime(df["ExpiryDate"])
    df["StrikePrice"] = pd.to_numeric(df["StrikePrice"], errors="coerce")
    df = df.dropna(subset=["StrikePrice"])
    print(f"Real contracts: {len(df)}")

    nearest = df["ExpiryDate"].min()
    near = df[df["ExpiryDate"] == nearest].copy()
    print(f"Nearest expiry: {nearest.date()} ({len(near)} contracts)")

    spot_df = ld.get_data("AAPL.O", ["TRDPRC_1"])
    spot_col = next(c for c in spot_df.columns if c != "Instrument")
    spot = float(spot_df[spot_col].iloc[0])
    print(f"Spot ({spot_col}): {spot:.2f}")

    lo, hi = spot * 0.85, spot * 1.15
    near = near[(near["StrikePrice"] >= lo) & (near["StrikePrice"] <= hi)]
    print(f"Contracts inside \u00b115%: {len(near)}")

    if near.empty:
        sys.exit("No contracts in strike window")

    end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    print(f"Fetching OI {start} \u2192 {end}")

    oi = ld.get_data(
        universe=near["RIC"].tolist(),
        fields=["TR.OPENINTEREST"],
        parameters={"SDate": start, "EDate": end, "Frq": "D"},
    )
    oi = oi.dropna(subset=["Open Interest"])
    latest = oi.groupby("Instrument", as_index=False).tail(1)

    merged = near.merge(latest, left_on="RIC", right_on="Instrument", how="inner")
    merged = merged.sort_values("StrikePrice")
    print(f"Contracts with OI: {len(merged)}")

    if merged.empty:
        sys.exit("No open interest data returned")

    # Plot 1: OI by strike
    fig1 = go.Figure()
    for side, color in [("Call", "#3ecbff"), ("Put", "#e8a317")]:
        sub = merged[merged["CallPutOption"] == side]
        fig1.add_trace(go.Bar(
            x=sub["StrikePrice"],
            y=sub["Open Interest"],
            name=side,
            marker_color=color,
        ))
    fig1.update_layout(
        title=f"AAPL OI by strike \u2014 {nearest.date()} (spot {spot:.2f})",
        xaxis_title="Strike",
        yaxis_title="Open Interest",
        barmode="group",
        template="plotly_dark",
        height=480,
    )
    fig1.write_html("docs/oi-by-strike.html", include_plotlyjs="cdn")

    # Plot 2: top walls
    walls = []
    for side in ("Call", "Put"):
        top = (merged[merged["CallPutOption"] == side]
               .nlargest(5, "Open Interest")[["StrikePrice", "Open Interest"]])
        top["side"] = side
        walls.append(top)
    walls = pd.concat(walls, ignore_index=True)

    fig2 = go.Figure(go.Bar(
        x=walls["Open Interest"],
        y=walls["StrikePrice"].astype(str) + " " + walls["side"],
        orientation="h",
        marker_color=["#3ecbff" if s == "Call" else "#e8a317" for s in walls["side"]],
    ))
    fig2.update_layout(
        title=f"Largest OI strikes \u2014 {nearest.date()}",
        xaxis_title="Open Interest",
        template="plotly_dark",
        height=420,
        margin=dict(l=120),
    )
    fig2.write_html("docs/oi-walls.html", include_plotlyjs="cdn")

    print("Wrote docs/oi-by-strike.html and docs/oi-walls.html")


if __name__ == "__main__":
    main()
