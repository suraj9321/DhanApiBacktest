#!/usr/bin/env python3
"""Analysis: intra-cycle theta decay curves, weekly vs monthly (5y averages).

Measure: ATM straddle as % of spot (cross-era comparable), sampled at 7 intraday
marks per session, averaged across all expiry cycles. X-axis: trading sessions
remaining to expiry (continuous: session index minus intraday progress).
Output: notes/attachments/theta-decay-curves.png + printed decay-share stats.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

Q = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
TODS = ["09:20", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
TOD_FRAC = {t: i / len(TODS) for i, t in enumerate(TODS)}  # 09:20 -> 0.0 … 15:15 -> 0.857

# palette (dataviz reference instance, light mode)
BLUE, INK, INK2, SURFACE, GRID = "#2a78d6", "#0b0b0b", "#52514e", "#fcfcfb", "#e8e8e6"


def load(flag: str, max_idx: int) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"""
        WITH bars AS (
          SELECT expiry_date, CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
                 strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod,
                 option_type, strike, close, spot
          FROM {Q}
          WHERE flag='{flag}' AND strike_offset=0 AND NOT special_session
            AND expiry_date IS NOT NULL
            AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') IN ({','.join(f"'{t}'" for t in TODS)})
        ),
        pairs AS (
          SELECT ce.expiry_date, ce.d, ce.tod,
                 (ce.close + pe.close) / ce.spot * 100 AS straddle_pct
          FROM (SELECT * FROM bars WHERE option_type='CE') ce
          JOIN (SELECT * FROM bars WHERE option_type='PE') pe
            USING (expiry_date, d, tod, strike)
        ),
        sess AS (
          SELECT expiry_date, d,
                 row_number() OVER (PARTITION BY expiry_date ORDER BY d DESC) - 1 AS idx
          FROM (SELECT DISTINCT expiry_date, d FROM pairs)
        )
        SELECT p.expiry_date, p.d, p.tod, p.straddle_pct, s.idx
        FROM pairs p JOIN sess s USING (expiry_date, d)
        WHERE s.idx <= {max_idx}
    """).fetchdf()
    df["x"] = df["idx"] - df["tod"].map(TOD_FRAC)  # sessions remaining, continuous
    return df


def curve(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("x")["straddle_pct"]
    return pd.DataFrame({
        "mean": g.mean(), "p25": g.quantile(0.25), "p75": g.quantile(0.75),
        "n": g.size(),
    }).reset_index().sort_values("x", ascending=False)


def session_decay(df: pd.DataFrame, steps: list[tuple[int, int]]) -> pd.DataFrame:
    """Mean decay (pct-of-spot points) between 15:15 marks of session pairs."""
    at_close = df[df["tod"] == "15:15"].pivot_table(
        index="expiry_date", columns="idx", values="straddle_pct")
    rows = []
    for a, b in steps:  # from session idx a to idx b (a > b)
        if a in at_close.columns and b in at_close.columns:
            d = (at_close[a] - at_close[b]).dropna() / (a - b)  # per-session rate
            rows.append({"step": f"{a}→{b}", "decay": d.mean(), "n": len(d)})
    return pd.DataFrame(rows)


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
    wk = load("week", 4)
    mo = load("month", 21)
    wc, mc = curve(wk), curve(mo)

    wd = session_decay(wk, [(4, 3), (3, 2), (2, 1), (1, 0)])
    md = session_decay(mo, [(21, 15), (15, 10), (10, 5), (5, 1), (1, 0)])

    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8), facecolor=SURFACE)
    fig.subplots_adjust(hspace=0.42, wspace=0.25, left=0.07, right=0.97, top=0.90, bottom=0.08)

    for ax, c, title in ((axes[0, 0], wc, "Weekly expiry — ATM straddle value through the cycle"),
                         (axes[0, 1], mc, "Monthly expiry — ATM straddle value through the cycle")):
        style(ax)
        ax.fill_between(c["x"], c["p25"], c["p75"], color=BLUE, alpha=0.14, linewidth=0)
        ax.plot(c["x"], c["mean"], color=BLUE, linewidth=2)
        ax.set_xticks(range(0, int(c["x"].max()) + 1, 1 if c["x"].max() < 6 else 5))
        ax.set_xlim(c["x"].max() + 0.15, c["x"].min() - 0.15)
        ax.set_title(title, color=INK, fontsize=11, loc="left", pad=10)
        ax.set_xlabel("trading sessions remaining to expiry", color=INK2, fontsize=9)
        ax.set_ylabel("ATM straddle, % of spot", color=INK2, fontsize=9)
        last = c.iloc[-1]
        ax.annotate("IQR band", xy=(float(c["x"].iloc[2]), float(c["p75"].iloc[2])),
                    color=INK2, fontsize=8, xytext=(0, 6), textcoords="offset points")

    for ax, d, title in ((axes[1, 0], wd, "Weekly — decay per session (15:15→15:15)"),
                         (axes[1, 1], md, "Monthly — decay per session, by phase (15:15→15:15)")):
        style(ax)
        bars = ax.bar(d["step"], d["decay"], color=BLUE, width=0.55)
        for b, v in zip(bars, d["decay"]):
            ax.annotate(f"{v:.2f}", xy=(b.get_x() + b.get_width() / 2, v),
                        ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_title(title, color=INK, fontsize=11, loc="left", pad=10)
        ax.set_xlabel("sessions-remaining step", color=INK2, fontsize=9)
        ax.set_ylabel("decay per session, % of spot", color=INK2, fontsize=9)

    fig.suptitle("Theta decay through the expiry cycle — Nifty ATM straddle, 5y averages (2021–2026)",
                 color=INK, fontsize=13, x=0.07, ha="left")

    out = Path("notes/attachments")
    out.mkdir(exist_ok=True)
    fig.savefig(out / "theta-decay-curves.png", dpi=150, facecolor=SURFACE)
    print(f"saved {out/'theta-decay-curves.png'}")

    for name, c in (("weekly", wc), ("monthly", mc)):
        total = c["mean"].iloc[0] - c["mean"].iloc[-1]
        for k in (1, 2):
            sub = c[c["x"] <= k]
            share = (sub["mean"].iloc[0] - sub["mean"].iloc[-1]) / total * 100
            print(f"{name}: last {k} session(s) hold {share:.0f}% of total cycle decay "
                  f"(entry {c['mean'].iloc[0]:.2f}% -> exit {c['mean'].iloc[-1]:.2f}%)")


if __name__ == "__main__":
    main()
