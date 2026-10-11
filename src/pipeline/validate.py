"""Data validation: every check answers one trust question before any backtest runs.

1. bar_integrity     — are sessions complete? (bars/day vs the trading-day set)
2. timestamp_sanity  — are bars inside session hours, without duplicates?
3. spot_crosscheck   — does the option-embedded spot agree with the independent
                       Nifty intraday series, minute by minute?
4. iv_consistency    — price-space check: repricing each option with the API's
                       own IV (Black-76 on the parity-implied forward, tau from
                       the empirical expiry calendar) should reproduce the
                       traded close. Validates IV, forward, and calendar jointly.
5. vix_check         — does our ATM weekly IV co-move with India VIX?

Detail tables land in meta.duckdb (validation_* tables); callers render the
summary dict into the vault report.
"""
from __future__ import annotations

import math

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config

OPTIONS_GLOB = str(config.PARQUET_DIR / "options" / "*" / "*" / "*.parquet")
SPOT_GLOB = str(config.PARQUET_DIR / "spot" / "nifty_intraday" / "*" / "*.parquet")
VIX_GLOB = str(config.PARQUET_DIR / "spot" / "indiavix_daily" / "*" / "*.parquet")


def bar_integrity(con: duckdb.DuckDBPyConnection) -> dict:
    dist = con.execute(
        f"""
        WITH per_day AS (
          SELECT flag, CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, count(*) AS bars
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          WHERE strike_offset = 0 AND option_type = 'CE'
          GROUP BY 1, 2
        )
        SELECT flag, bars, count(*) AS days FROM per_day GROUP BY 1, 2 ORDER BY 1, 3 DESC
        """
    ).fetchdf()

    missing = con.execute(
        f"""
        WITH opt_days AS (
          SELECT DISTINCT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          WHERE strike_offset = 0 AND option_type = 'CE' AND flag = 'week'
        ),
        spot_days AS (
          SELECT DISTINCT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d
          FROM read_parquet('{SPOT_GLOB}')
          WHERE CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE)
                BETWEEN (SELECT min(d) FROM opt_days) AND (SELECT max(d) FROM opt_days)
        )
        SELECT
          (SELECT count(*) FROM spot_days WHERE d NOT IN (SELECT d FROM opt_days)) AS spot_days_missing_in_options,
          (SELECT count(*) FROM opt_days  WHERE d NOT IN (SELECT d FROM spot_days)) AS option_days_missing_in_spot
        """
    ).fetchdf()

    duckdb.connect(str(config.META_DB)).execute(
        "CREATE OR REPLACE TABLE validation_bar_distribution AS SELECT * FROM dist"
    ).close()
    return {"distribution": dist, "day_mismatch": missing}


def timestamp_sanity(con: duckdb.DuckDBPyConnection) -> dict:
    tod = con.execute(
        f"""
        SELECT
          min(strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M')) AS first_bar,
          max(strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M')) AS last_bar,
          count(*) AS rows
        FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
        """
    ).fetchdf()
    dups = con.execute(
        f"""
        SELECT count(*) AS dup_keys FROM (
          SELECT flag, option_type, strike_offset, ts, count(*) c
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          GROUP BY 1,2,3,4 HAVING count(*) > 1
        )
        """
    ).fetchdf()
    return {"time_of_day": tod, "duplicates": int(dups["dup_keys"][0])}


def spot_crosscheck(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        f"""
        WITH o AS (
          SELECT ts, spot
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          WHERE strike_offset = 0 AND option_type = 'CE' AND flag = 'week'
        ),
        s AS (SELECT ts, close FROM read_parquet('{SPOT_GLOB}'))
        SELECT count(*)                                        AS joined_minutes,
               round(quantile_cont(abs(o.spot - s.close), 0.5), 3)  AS abs_diff_p50,
               round(quantile_cont(abs(o.spot - s.close), 0.99), 3) AS abs_diff_p99,
               round(max(abs(o.spot - s.close)), 3)                 AS abs_diff_max,
               round(100.0 * quantile_cont(abs(o.spot - s.close) / s.close, 0.99), 4) AS pct_diff_p99
        FROM o JOIN s USING (ts)
        """
    ).fetchdf()


def _black76(F, K, tau, sigma, is_call):
    """Vectorized Black-76 (r=0: discounting negligible at <=35 DTE for validation)."""
    F, K, tau, sigma = (np.asarray(x, dtype=float) for x in (F, K, tau, sigma))
    tiny = (tau <= 0) | (sigma <= 0)
    tau_ = np.where(tiny, 1e-9, tau)
    sig_ = np.where(tiny, 1e-9, sigma)
    st = sig_ * np.sqrt(tau_)
    d1 = (np.log(F / K) + 0.5 * st**2) / st
    d2 = d1 - st
    call = F * norm.cdf(d1) - K * norm.cdf(d2)
    put = K * norm.cdf(-d2) - F * norm.cdf(-d1)
    intrinsic = np.where(is_call, np.maximum(F - K, 0), np.maximum(K - F, 0))
    px = np.where(is_call, call, put)
    return np.where(tiny, intrinsic, px)


def iv_consistency(con: duckdb.DuckDBPyConnection) -> dict:
    """Sample: 15:15 IST bar daily, offsets -5..+5, weekly flag.

    Forward from ATM parity at the same minute (F = K_atm + CE - PE), tau to
    expiry-day 15:30 IST from the empirical calendar, reprice with API IV.
    """
    meta = duckdb.connect(str(config.META_DB), read_only=True)
    cal = meta.execute(
        "SELECT expiry_date FROM expiry_calendar WHERE flag = 'week' ORDER BY 1"
    ).fetchdf()
    meta.close()
    expiries = pd.to_datetime(cal["expiry_date"]).dt.date.values

    df = con.execute(
        f"""
        SELECT flag, option_type, strike_offset, ts, close, spot, strike, iv,
               CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d
        FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
        WHERE flag = 'week' AND strike_offset BETWEEN -5 AND 5
          AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') = '15:15'
        """
    ).fetchdf()

    # Map each trade date to its expiry (next expiry >= date) and tau in years.
    d_dates = pd.to_datetime(df["d"]).dt.date.values
    idx = np.searchsorted(expiries, d_dates, side="left")
    valid = idx < len(expiries)
    df = df[valid].copy()
    exp_for_row = expiries[idx[valid]]
    df["expiry_date"] = exp_for_row
    df["dte"] = (pd.to_datetime(df["expiry_date"]) - pd.to_datetime(df["d"])).dt.days
    # 15:15 sample bar -> settlement 15:30 on expiry day.
    df["tau"] = (df["dte"] * 86400 + 15 * 60) / (365.0 * 86400)

    # Implied forward per (d): ATM pair at the same minute.
    atm = df[df["strike_offset"] == 0].pivot_table(
        index="d", columns="option_type", values=["close", "strike"], aggfunc="first"
    )
    atm.columns = ["_".join(c) for c in atm.columns]
    atm = atm.dropna(subset=["close_CE", "close_PE"])
    atm = atm[atm["strike_CE"] == atm["strike_PE"]]
    atm["fwd"] = atm["strike_CE"] + atm["close_CE"] - atm["close_PE"]
    df = df.merge(atm[["fwd"]], left_on="d", right_index=True, how="inner")

    df["model"] = _black76(
        df["fwd"], df["strike"], df["tau"], df["iv"] / 100.0, df["option_type"] == "CE"
    )
    df["abs_err"] = (df["model"] - df["close"]).abs()
    df["rel_err"] = df["abs_err"] / df["close"].clip(lower=1.0)  # floor tiny premiums

    by_dte = (
        df.groupby("dte")
        .agg(n=("rel_err", "size"), rel_err_p50=("rel_err", "median"),
             rel_err_p90=("rel_err", lambda s: s.quantile(0.9)),
             abs_err_p50=("abs_err", "median"))
        .reset_index()
    )
    meta = duckdb.connect(str(config.META_DB))
    meta.execute("CREATE OR REPLACE TABLE validation_iv_consistency AS SELECT * FROM df")
    meta.close()
    return {"by_dte": by_dte, "n_total": len(df)}


def vix_check(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        f"""
        WITH atm_iv AS (
          SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, avg(iv) AS atm_iv
          FROM read_parquet('{OPTIONS_GLOB}', hive_partitioning=true)
          WHERE flag = 'week' AND strike_offset = 0
            AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') = '15:15'
          GROUP BY 1
        ),
        vix AS (
          SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, close AS vix
          FROM read_parquet('{VIX_GLOB}')
        )
        SELECT count(*) AS days,
               round(corr(atm_iv, vix), 3)        AS correlation,
               round(avg(atm_iv - vix), 2)        AS mean_spread_atm_minus_vix,
               round(avg(atm_iv), 2) AS mean_atm_iv, round(avg(vix), 2) AS mean_vix
        FROM atm_iv JOIN vix USING (d)
        """
    ).fetchdf()
