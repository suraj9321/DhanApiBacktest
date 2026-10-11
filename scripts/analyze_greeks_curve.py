#!/usr/bin/env python3
"""Greeks through the expiry cycle — companion to analyze_theta_curve.py.

Four panels, ATM straddle means across all cycles (2021-2026), weekly vs
monthly overlaid on a shared sessions-remaining axis:
  1. Gamma  — delta gained per 1% spot move (the risk accelerant)
  2. Theta  — model decay per calendar day, % of spot (the payment)
  3. Vega   — pts per vol-point, % of spot (the IV exposure)
  4. Delta polarization — CE delta at fixed offsets +1..+4 (weekly): how the
     same rupee distance 'hardens' as tau shrinks (strike-selection input).
Output: notes/attachments/greeks-curves.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

Q = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
TODS = ["09:20", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
TOD_FRAC = {t: i / len(TODS) for i, t in enumerate(TODS)}

BLUE, GREEN = "#2a78d6", "#008300"           # weekly, monthly (validated pair)
SEQ = ["#9ec4ec", "#6ba3e0", "#2a78d6", "#174f96"]  # single-hue steps for offsets +1..+4
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e8e8e6"


def load(flag: str, max_idx: int) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"""
        WITH bars AS (
          SELECT expiry_date, CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
                 strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod,
                 option_type, strike_offset, strike, spot, fwd,
                 delta, gamma, vega, theta_day
          FROM {Q}
          WHERE flag='{flag}' AND NOT special_session AND NOT settlement_window
            AND expiry_date IS NOT NULL AND delta IS NOT NULL
            AND strike_offset BETWEEN 0 AND 4
            AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') IN ({','.join(f"'{t}'" for t in TODS)})
        ),
        sess AS (
          SELECT expiry_date, d,
                 row_number() OVER (PARTITION BY expiry_date ORDER BY d DESC) - 1 AS idx
          FROM (SELECT DISTINCT expiry_date, d FROM bars)
        )
        SELECT b.*, s.idx FROM bars b JOIN sess s USING (expiry_date, d)
        WHERE s.idx <= {max_idx}
    """).fetchdf()
    df["x"] = df["idx"] - df["tod"].map(TOD_FRAC)
    return df


def atm_straddle_curves(df: pd.DataFrame) -> pd.DataFrame:
    atm = df[df["strike_offset"] == 0]
    pair = atm.pivot_table(index=["expiry_date", "d", "tod", "x"], columns="option_type",
                           values=["gamma", "vega", "theta_day", "spot", "fwd"], aggfunc="first")
    pair.columns = ["_".join(c) for c in pair.columns]
    pair = pair.dropna().reset_index()
    pair["gamma_1pct"] = (pair["gamma_CE"] + pair["gamma_PE"]) * 0.01 * pair["fwd_CE"]
    pair["vega_pctspot"] = (pair["vega_CE"] + pair["vega_PE"]) / pair["spot_CE"] * 100
    pair["theta_pctspot"] = (pair["theta_day_CE"].abs() + pair["theta_day_PE"].abs()) / pair["spot_CE"] * 100
    g = pair.groupby("x")[["gamma_1pct", "vega_pctspot", "theta_pctspot"]].mean().reset_index()
    return g.sort_values("x", ascending=False)


def delta_by_offset(df: pd.DataFrame) -> pd.DataFrame:
    ce = df[(df["option_type"] == "CE") & (df["strike_offset"].between(1, 4))]
    return (ce.groupby(["strike_offset", "x"])["delta"].mean().reset_index()
              .sort_values(["strike_offset", "x"], ascending=[True, False]))


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def main() -> None:
    wk, mo = load("week", 4), load("month", 21)
    wc, mc = atm_straddle_curves(wk), atm_straddle_curves(mo)
    dd = delta_by_offset(wk)

    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.2), facecolor=SURFACE)
    fig.subplots_adjust(hspace=0.44, wspace=0.26, left=0.07, right=0.97, top=0.88, bottom=0.08)

    panels = [
        (axes[0, 0], "gamma_1pct", "Gamma — ATM straddle delta gained per 1% spot move"),
        (axes[0, 1], "theta_pctspot", "Theta — ATM straddle model decay per day, % of spot"),
        (axes[1, 0], "vega_pctspot", "Vega — ATM straddle pts per vol-point, % of spot"),
    ]
    for ax, col, title in panels:
        style(ax)
        ax.plot(mc["x"], mc[col], color=GREEN, linewidth=2, label="monthly")
        ax.plot(wc["x"], wc[col], color=BLUE, linewidth=2, label="weekly")
        ax.set_xticks(range(0, 22, 5))
        ax.set_xlim(21.2, -1.0)
        ax.set_title(title, color=INK, fontsize=10.5, loc="left", pad=10)
        ax.set_xlabel("trading sessions remaining to expiry", color=INK2, fontsize=9)
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")

    ax = axes[1, 1]
    style(ax)
    for off, color in zip((1, 2, 3, 4), SEQ):
        sub = dd[dd["strike_offset"] == off]
        ax.plot(sub["x"], sub["delta"], color=color, linewidth=2)
        dy = {1: 0, 2: 4, 3: 10, 4: -6}[off]
        ax.annotate(f"ATM+{off}", xy=(float(sub["x"].iloc[-1]), float(sub["delta"].iloc[-1])),
                    xytext=(6, dy), textcoords="offset points", color=color, fontsize=9,
                    va="center")
    ax.set_xticks(range(0, 5))
    ax.set_xlim(4.2, -1.3)
    ax.set_title("Delta polarization — weekly CE delta at fixed strike offsets",
                 color=INK, fontsize=10.5, loc="left", pad=10)
    ax.set_xlabel("trading sessions remaining to expiry", color=INK2, fontsize=9)

    fig.suptitle("Greeks through the expiry cycle — Nifty ATM structures, 5y averages (2021–2026)",
                 color=INK, fontsize=13, x=0.07, ha="left")
    out = Path("notes/attachments")
    out.mkdir(exist_ok=True)
    fig.savefig(out / "greeks-curves.png", dpi=150, facecolor=SURFACE)
    print(f"saved {out/'greeks-curves.png'}")

    for name, c in (("weekly", wc), ("monthly", mc)):
        first, last = c.iloc[0], c.iloc[-1]
        print(f"{name}: gamma {first['gamma_1pct']:.3f}->{last['gamma_1pct']:.3f} "
              f"(x{last['gamma_1pct']/first['gamma_1pct']:.1f}), "
              f"vega {first['vega_pctspot']:.3f}->{last['vega_pctspot']:.3f}%, "
              f"theta {first['theta_pctspot']:.3f}->{last['theta_pctspot']:.3f}%/day")


if __name__ == "__main__":
    main()
