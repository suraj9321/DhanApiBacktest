#!/usr/bin/env python3
"""Analysis 1: overnight & weekend gap distribution for Nifty (daily, 2006->).

The Fri-close -> Mon-open gap is the risk we hold, unhedgeable and
unadjustable, in the Friday->Tuesday trade window. Stops cannot execute
through it; only wings bound it. This script tabulates its distribution over
~20 years, split by session-gap type, for the full history and the recent 5y.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

DAILY = "read_parquet('data/parquet/spot/nifty_daily/*/*.parquet')"


def load() -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(
        f"""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, open, close
        FROM {DAILY} ORDER BY d
        """
    ).fetchdf()
    df["prev_close"] = df["close"].shift(1)
    df["prev_d"] = df["d"].shift(1)
    df["span"] = (pd.to_datetime(df["d"]) - pd.to_datetime(df["prev_d"])).dt.days
    df["gap_pct"] = (df["open"] / df["prev_close"] - 1) * 100
    df["bucket"] = pd.cut(
        df["span"], bins=[0, 1, 2, 3, 99],
        labels=["overnight(1d)", "two-day", "weekend(3d)", "long-weekend(4d+)"],
    )
    return df.dropna(subset=["gap_pct", "bucket"])


def stats(df: pd.DataFrame, label: str) -> None:
    print(f"\n=== {label} ===")
    g = df.groupby("bucket", observed=True)["gap_pct"]
    out = g.agg(
        n="size", mean="mean", sd="std",
        p01=lambda s: s.quantile(0.01), p05=lambda s: s.quantile(0.05),
        p50="median",
        p95=lambda s: s.quantile(0.95), p99=lambda s: s.quantile(0.99),
        min="min", max="max",
    ).round(2)
    print(out.to_string())
    wk = df[df["bucket"].isin(["weekend(3d)", "long-weekend(4d+)"])]["gap_pct"]
    for t in (1, 2, 3, 5):
        pct = 100 * (wk.abs() > t).mean()
        print(f"  P(|weekend gap| > {t}%) = {pct:.2f}%   (~1 in {1/max(pct/100, 1e-9):.0f} weekends)")


def main() -> None:
    df = load()
    stats(df, "FULL HISTORY 2006-2026 (~20y)")
    stats(df[pd.to_datetime(df["d"]) >= pd.Timestamp("2021-07-01")], "RECENT 5Y (options-data era)")

    wk = df[df["bucket"].isin(["weekend(3d)", "long-weekend(4d+)"])]
    print("\n=== 12 worst weekend/holiday gaps (full history) ===")
    worst = wk.reindex(wk["gap_pct"].abs().sort_values(ascending=False).index)
    print(worst.head(12)[["prev_d", "d", "span", "gap_pct"]]
          .assign(gap_pct=lambda x: x["gap_pct"].round(2)).to_string(index=False))

    spot = df["close"].iloc[-1]
    p99 = wk["gap_pct"].quantile(0.01), wk["gap_pct"].quantile(0.99)
    print(f"\nAt current Nifty ~{spot:.0f}: 1%/99% weekend gap = "
          f"{p99[0]:.2f}% / {p99[1]:.2f}% = {spot*p99[0]/100:+.0f} / {spot*p99[1]/100:+.0f} points")


if __name__ == "__main__":
    main()
