"""Empirical expiry-day detection from the options data itself.

Why not hardcode NSE rules: the weekly expiry weekday changed in 2025, and
holidays shift expiries to the previous session. Any rule table we write is a
liability; the data already knows. On expiry day the ATM straddle's *time
value* (CE + PE - |spot - strike|) collapses to ~0 by the last bar of the
session; on all other days the front weekly straddle carries well over
EXPIRY_TV_THRESHOLD points of overnight value. Thresholding cleanly labels
every session, and the resulting weekday histogram makes rule changes visible
instead of assumed.

Output: `expiry_calendar` table in meta.duckdb (flag, expiry_date, weekday,
straddle_tv) — consumed by validation and by the Greeks enrichment (tau).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from . import config

OPTIONS_GLOB = str(config.PARQUET_DIR / "options" / "*" / "*" / "*.parquet")


def day_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per (flag, trade_date): last-bar ATM straddle time value."""
    return con.execute(
        f"""
        WITH bars AS (
          SELECT flag, option_type, ts, close, spot, strike,
                 CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          WHERE strike_offset = 0
        ),
        last_bars AS (
          SELECT flag, option_type, d,
                 arg_max(close, ts)  AS close,
                 arg_max(spot, ts)   AS spot,
                 arg_max(strike, ts) AS strike
          FROM bars GROUP BY 1, 2, 3
        )
        SELECT ce.flag,
               ce.d                                            AS trade_date,
               ce.close + pe.close - abs(ce.spot - ce.strike)  AS straddle_tv,
               ce.spot, ce.strike,
               dayname(ce.d)                                   AS weekday
        FROM (SELECT * FROM last_bars WHERE option_type = 'CE') ce
        JOIN (SELECT * FROM last_bars WHERE option_type = 'PE') pe
          ON ce.flag = pe.flag AND ce.d = pe.d AND ce.strike = pe.strike
        ORDER BY ce.flag, ce.d
        """
    ).fetchdf()


def build(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    con = con or duckdb.connect()
    days = day_table(con)

    # Detection = cadence + roll-jump. Absolute time value fails on violent
    # expiry days (May 2025 war week: expiry-day close straddle held 120 pts of
    # settlement uncertainty), but the roll is unmistakable: the session AFTER
    # expiry the front contract gains ~a week of life, so TV jumps several-fold.
    # Within each period (one expiry per ISO week / calendar month) pick the day
    # maximizing next_tv / tv. Data-edge periods (no next session for the true
    # expiry, jump unknowable) fail EXPIRY_JUMP_MIN and are rejected.
    days = days.sort_values(["flag", "trade_date"]).reset_index(drop=True)
    days["next_tv"] = days.groupby("flag")["straddle_tv"].shift(-1)
    days["jump"] = days["next_tv"] / days["straddle_tv"].clip(lower=5.0)
    td = pd.to_datetime(days["trade_date"])
    days["period"] = np.where(
        days["flag"] == "week",
        td.dt.strftime("%G-W%V"),
        td.dt.strftime("%Y-%m"),
    )
    idx = days.groupby(["flag", "period"])["jump"].idxmax().dropna()
    cal = (
        days.loc[idx]
        .query("jump > @config.EXPIRY_JUMP_MIN")
        .rename(columns={"trade_date": "expiry_date"})
        [["flag", "expiry_date", "weekday", "straddle_tv", "jump"]]
        .sort_values(["flag", "expiry_date"])
        .reset_index(drop=True)
    )

    meta = duckdb.connect(str(config.META_DB))
    meta.execute("CREATE OR REPLACE TABLE expiry_calendar AS SELECT * FROM cal")
    meta.execute("CREATE OR REPLACE TABLE expiry_day_detail AS SELECT * FROM days")
    meta.close()
    return cal


def summary(cal: pd.DataFrame) -> str:
    lines = []
    for flag, grp in cal.groupby("flag"):
        wd = grp["weekday"].value_counts().to_dict()
        lines.append(
            f"{flag}: {len(grp)} expiries "
            f"({grp['expiry_date'].min()} .. {grp['expiry_date'].max()}), weekdays: {wd}"
        )
    return "\n".join(lines)
