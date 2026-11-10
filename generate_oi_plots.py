#!/usr/bin/env python3
"""
Fetch options open-interest grids via LSEG and write interactive Plotly figures
that surface OI clusters (put walls, call walls, pinning candidates).

Credentials are read from the environment (GitHub Actions secrets):
  LSEG_APP_KEY, LSEG_USERNAME, LSEG_PASSWORD

The script writes self-contained HTML plots into docs/ so the site can embed them.
"""

import os
import sys
import time
from typing import Tuple

import lseg.data as ld
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from lseg.data.discovery import Chain
from plotly.subplots import make_subplots


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


def get_options_oi_grids(
    chain_ric: str,
    underlying_ric: str,
    moneyness_decimals: int = 2,
    chunk_size: int = 200,
    sleep_between_chunks: float = 0.5,
    min_oi: int = 0,
) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    chain = Chain(name=chain_ric)
    rics = list(chain.constituents)
    if not rics:
        raise ValueError(f"No constituents found for chain {chain_ric}")

    print(f"Found {len(rics)} option RICs in {chain_ric}")

    fields = ["EXPIR_DATE", "STRIKE_PRC", "PUT_CALL", "PUTCALLIND", "OPINT_1"]
    dfs = []

    for i in range(0, len(rics), chunk_size):
        chunk = rics[i : i + chunk_size]
        try:
            df_chunk = ld.get_data(universe=chunk, fields=fields)
            if df_chunk is not None and not df_chunk.empty:
                dfs.append(df_chunk)
        except Exception as e:
            print(f"Chunk {i // chunk_size + 1} failed: {e}")
        if sleep_between_chunks:
            time.sleep(sleep_between_chunks)

    if not dfs:
        raise RuntimeError("No option data returned")

    raw = pd.concat(dfs, ignore_index=True)

    if "PUT_CALL" in raw.columns:
        raw["put_call"] = raw["PUT_CALL"].astype(str).str.upper().str.strip()
    elif "PUTCALLIND" in raw.columns:
        raw["put_call"] = raw["PUTCALLIND"].astype(str).str.upper().str.strip()
    else:
        raise ValueError("Neither PUT_CALL nor PUTCALLIND field returned")

    raw["put_call"] = raw["put_call"].replace({
        "C": "CALL", "CALL": "CALL",
        "P": "PUT", "PUT": "PUT",
    })
    raw = raw[raw["put_call"].isin(["CALL", "PUT"])].copy()

    raw["STRIKE_PRC"] = pd.to_numeric(raw["STRIKE_PRC"], errors="coerce")
    raw["OPINT_1"] = pd.to_numeric(raw["OPINT_1"], errors="coerce").fillna(0)
    raw["EXPIR_DATE"] = pd.to_datetime(raw["EXPIR_DATE"], errors="coerce")

    raw = raw.dropna(subset=["STRIKE_PRC", "EXPIR_DATE"])
    raw = raw[raw["OPINT_1"] >= min_oi]

    spot_df = ld.get_data(universe=[underlying_ric], fields=["TRDPRC_1"])
    if spot_df is None or spot_df.empty or pd.isna(spot_df["TRDPRC_1"].iloc[0]):
        hist = ld.get_history(universe=underlying_ric, fields=["TRDPRC_1"], count=1)
        spot = float(hist["TRDPRC_1"].iloc[-1])
    else:
        spot = float(spot_df["TRDPRC_1"].iloc[0])

    print(f"Underlying spot ({underlying_ric}): {spot}")

    raw["moneyness"] = (raw["STRIKE_PRC"] / spot).round(moneyness_decimals)

    def pivot_oi(df_side: pd.DataFrame) -> pd.DataFrame:
        if df_side.empty:
            return pd.DataFrame()
        pivoted = df_side.pivot_table(
            index="EXPIR_DATE",
            columns="moneyness",
            values="OPINT_1",
            aggfunc="sum",
            fill_value=0,
        )
        pivoted = pivoted.sort_index()
        pivoted = pivoted.reindex(sorted(pivoted.columns), axis=1)
        pivoted.index = pivoted.index.strftime("%Y-%m-%d")
        return pivoted

    calls = raw[raw["put_call"] == "CALL"]
    puts = raw[raw["put_call"] == "PUT"]

    return pivot_oi(calls), pivot_oi(puts), spot


def find_clusters(oi: pd.DataFrame, side: str, top_n: int = 5) -> pd.DataFrame:
    """Return the heaviest OI cells and a simple wall summary."""
    if oi.empty:
        return pd.DataFrame()
    flat = oi.stack().reset_index()
    flat.columns = ["expiry", "moneyness", "oi"]
    flat = flat[flat["oi"] > 0].sort_values("oi", ascending=False)
    top = flat.head(top_n).copy()
    top["side"] = side
    # Simple wall: moneyness of the single largest OI strike (aggregated across expiries)
    by_m = oi.sum(axis=0).sort_values(ascending=False)
    wall_m = float(by_m.index[0]) if len(by_m) else np.nan
    top["wall_moneyness"] = wall_m
    top["wall_total_oi"] = float(by_m.iloc[0]) if len(by_m) else 0
    return top


def make_heatmap(oi: pd.DataFrame, title: str, spot: float) -> go.Figure:
    if oi.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} — no data")
        return fig

    z = oi.values
    x = [f"{c:.2f}" for c in oi.columns]
    y = list(oi.index)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x,
            y=y,
            colorscale="Viridis",
            hovertemplate="Expiry: %{y}<br>Moneyness: %{x}<br>OI: %{z:,.0f}<extra></extra>",
            colorbar=dict(title="Open Interest"),
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Moneyness (strike / spot)",
        yaxis_title="Expiry",
        height=520,
        margin=dict(l=60, r=40, t=60, b=60),
    )
    # Mark ATM
    fig.add_vline(x="1.00", line_dash="dash", line_color="orange", annotation_text="ATM")
    return fig


def make_wall_bars(calls_oi: pd.DataFrame, puts_oi: pd.DataFrame, spot: float) -> go.Figure:
    call_tot = calls_oi.sum(axis=0) if not calls_oi.empty else pd.Series(dtype=float)
    put_tot = puts_oi.sum(axis=0) if not puts_oi.empty else pd.Series(dtype=float)
    all_m = sorted(set(call_tot.index) | set(put_tot.index))
    call_vals = [float(call_tot.get(m, 0)) for m in all_m]
    put_vals = [float(put_tot.get(m, 0)) for m in all_m]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=[f"{m:.2f}" for m in all_m], y=call_vals, name="Calls", marker_color="#7cff55"))
    fig.add_trace(go.Bar(x=[f"{m:.2f}" for m in all_m], y=put_vals, name="Puts", marker_color="#ff6b6b"))
    fig.update_layout(
        title=f"Total open interest by moneyness (spot ≈ {spot:.2f})",
        xaxis_title="Moneyness",
        yaxis_title="Sum of OI across expiries",
        barmode="group",
        height=420,
        legend=dict(orientation="h"),
    )
    fig.add_vline(x="1.00", line_dash="dash", line_color="orange")
    return fig


def write_plots(calls_oi: pd.DataFrame, puts_oi: pd.DataFrame, spot: float, out_dir: str = "docs") -> None:
    os.makedirs(out_dir, exist_ok=True)

    call_clusters = find_clusters(calls_oi, "CALL")
    put_clusters = find_clusters(puts_oi, "PUT")

    heat_calls = make_heatmap(calls_oi, "Call open interest by expiry and moneyness", spot)
    heat_puts = make_heatmap(puts_oi, "Put open interest by expiry and moneyness", spot)
    walls = make_wall_bars(calls_oi, puts_oi, spot)

    # Annotate the bar chart with the heaviest clusters
    notes = []
    if not call_clusters.empty:
        m = call_clusters["wall_moneyness"].iloc[0]
        notes.append(f"Heaviest call concentration near moneyness {m:.2f} (approx strike {m*spot:.1f})")
    if not put_clusters.empty:
        m = put_clusters["wall_moneyness"].iloc[0]
        notes.append(f"Heaviest put concentration near moneyness {m:.2f} (approx strike {m*spot:.1f})")
    if notes:
        walls.add_annotation(
            text="<br>".join(notes),
            xref="paper", yref="paper",
            x=0.01, y=0.99,
            showarrow=False,
            align="left",
            bgcolor="rgba(6,20,51,0.85)",
            bordercolor="#d4a017",
            font=dict(size=11, color="#e8eefc"),
        )

    heat_calls.write_html(os.path.join(out_dir, "oi-calls.html"), include_plotlyjs="cdn", full_html=True)
    heat_puts.write_html(os.path.join(out_dir, "oi-puts.html"), include_plotlyjs="cdn", full_html=True)
    walls.write_html(os.path.join(out_dir, "oi-walls.html"), include_plotlyjs="cdn", full_html=True)

    # Also dump the cluster tables for the page or later use
    clusters = pd.concat([call_clusters, put_clusters], ignore_index=True)
    clusters.to_csv(os.path.join(out_dir, "oi-clusters.csv"), index=False)
    print(f"Wrote plots and oi-clusters.csv to {out_dir}/")


def main() -> None:
    chain = os.environ.get("OI_CHAIN_RIC", "0#AAPL*.U")
    underlying = os.environ.get("OI_UNDERLYING_RIC", "AAPL.O")
    open_lseg_session()
    calls_oi, puts_oi, spot = get_options_oi_grids(chain, underlying, min_oi=1)
    write_plots(calls_oi, puts_oi, spot)
    print("Done")


if __name__ == "__main__":
    main()
