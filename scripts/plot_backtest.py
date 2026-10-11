#!/usr/bin/env python3
"""Visualize a backtest run from its saved ledgers.

Usage: python scripts/plot_backtest.py weekly_v01
Reads  data/backtest_<name>_{equity,trades}.parquet
Writes notes/attachments/backtest-<name>.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

BLUE, RED = "#2a78d6", "#e34948"           # diverging poles (validated palette)
ORANGE = "#eb6834"                          # categorical slot 6 (costs series)
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e8e8e6"


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
    name = sys.argv[1] if len(sys.argv) > 1 else "weekly_v01"
    eq = pd.read_parquet(f"data/backtest_{name}_equity.parquet")
    tr = pd.read_parquet(f"data/backtest_{name}_trades.parquet")
    eq["d"] = pd.to_datetime(eq["d"])
    exits = tr[tr["event"] == "exit"].copy()
    exits["d"] = pd.to_datetime(exits["d"])
    entries = tr[tr["event"] == "entry"]

    # cost series aligned to exits (approximate per-trade costs: total/n spread evenly
    # is dishonest — recompute per trade from ledger structure: entry+exit ~8 orders;
    # we saved only totals, so show cumulative gross vs cumulative net instead).
    exits = exits.sort_values("d")
    exits["cum_gross"] = exits["pnl_gross"].cumsum()

    fig, axes = plt.subplots(2, 2, figsize=(12.5, 8), facecolor=SURFACE)
    fig.subplots_adjust(hspace=0.45, wspace=0.24, left=0.08, right=0.97, top=0.88, bottom=0.09)

    # 1. equity curve
    ax = axes[0, 0]
    style(ax)
    ax.plot(eq["d"], eq["equity"] / 1e5, color=BLUE, linewidth=2)
    ax.axhline(8.0, color=INK2, linewidth=0.8, linestyle="--")
    ax.annotate("capital ₹8L", xy=(eq["d"].iloc[5], 8.0), xytext=(0, 5),
                textcoords="offset points", fontsize=8, color=INK2)
    ax.set_title("Equity curve (₹ lakh)", color=INK, fontsize=11, loc="left", pad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 2. drawdown
    ax = axes[0, 1]
    style(ax)
    dd = 100 * (eq["equity"] - eq["equity"].cummax()) / eq["equity"].cummax()
    ax.fill_between(eq["d"], dd, 0, color=RED, alpha=0.25, linewidth=0)
    ax.plot(eq["d"], dd, color=RED, linewidth=1.5)
    ax.set_title("Drawdown from peak (%)", color=INK, fontsize=11, loc="left", pad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 3. per-trade P&L (diverging by sign)
    ax = axes[1, 0]
    style(ax)
    colors = np.where(exits["pnl_gross"] >= 0, BLUE, RED)
    ax.bar(exits["d"], exits["pnl_gross"], width=5, color=colors)
    ax.set_title("Per-trade gross P&L (₹) — blue win / red loss",
                 color=INK, fontsize=11, loc="left", pad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 4. cumulative gross vs net (the cost bleed made visible)
    ax = axes[1, 1]
    style(ax)
    ax.plot(exits["d"], exits["cum_gross"] / 1e3, color=BLUE, linewidth=2, label="cumulative gross P&L")
    net = eq.set_index("d")["equity"] - 8e5
    ax.plot(net.index, net.values / 1e3, color=ORANGE, linewidth=2, label="cumulative net (after costs)")
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_title("Gross vs net P&L (₹ thousand) — the gap is costs",
                 color=INK, fontsize=11, loc="left", pad=10)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="best")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    n, wins = len(exits), int((exits["pnl_gross"] > 0).sum())
    fig.suptitle(f"Backtest: {name} — {n} trades, {wins} wins, "
                 f"final ₹{eq['equity'].iloc[-1]:,.0f}",
                 color=INK, fontsize=13, x=0.08, ha="left")

    out = Path("notes/attachments") / f"backtest-{name}.png"
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
