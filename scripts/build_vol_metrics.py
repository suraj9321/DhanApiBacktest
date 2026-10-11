#!/usr/bin/env python3
"""Build the daily vol/VRP signal table and print forecast diagnostics."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipeline import vol_metrics  # noqa: E402


def main() -> None:
    sig = vol_metrics.build_signals()
    print(f"signal table: {len(sig)} days ({sig['d'].min()} .. {sig['d'].max()}) "
          f"-> {vol_metrics.SIGNALS_PATH}")

    # Forecast quality vs subsequently realized 5-session vol (evaluation only).
    ev = sig.dropna(subset=["rv_fwd5_EVAL", "iv_week_1515"])
    print("\n--- forecaster vs realized next-5-session vol (2021+ IV era) ---")
    for col in ("rv_har5", "rv_ewma", "rv_garch", "rv_cc21", "iv_week_1515", "cm7_iv", "vix"):
        sub = ev.dropna(subset=[col])
        corr = sub[col].corr(sub["rv_fwd5_EVAL"])
        mae = (sub[col] - sub["rv_fwd5_EVAL"]).abs().mean()
        bias = (sub[col] - sub["rv_fwd5_EVAL"]).mean()
        print(f"  {col:12s} corr {corr:5.2f}   MAE {mae:5.2f}   bias {bias:+5.2f}  (n={len(sub)})")

    print("\n--- VRP (weekly ATM IV - RV blend forecast), by year ---")
    vr = sig.dropna(subset=["vrp_week"]).copy()
    vr["year"] = pd.to_datetime(vr["d"]).dt.year
    print(vr.groupby("year")["vrp_week"].agg(["mean", "median",
          lambda s: 100 * (s > 0).mean()]).rename(columns={"<lambda_0>": "pct_pos"}).round(2).to_string())

    last = sig.dropna(subset=["iv_week_1515"]).iloc[-1]
    print(f"\n--- latest snapshot ({last['d']}) ---")
    for k in ("iv_week_1515", "iv_month_1515", "cm7_iv", "cm30_iv", "vix",
              "rv_har5", "rv_ewma", "rv_garch", "vrp_week", "vrp_z", "iv_rank_1y", "term_slope"):
        v = last[k]
        print(f"  {k:14s} {v:7.2f}" if np.isfinite(v) else f"  {k:14s}     n/a")


if __name__ == "__main__":
    main()
