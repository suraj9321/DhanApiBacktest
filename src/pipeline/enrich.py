"""Greeks enrichment: base parquet + empirical expiry calendar -> options_enriched.

Adds per-bar columns: expiry_date, tau (years, ACT/365, bar-close to 15:30 IST
settlement), fwd (parity-implied forward), delta, gamma, vega, theta_day, and
two session flags (settlement_window: tau <= 15 min; special_session: Muhurat
evening bars). Base parquet and raw JSON are never modified.

Conventions (must match validate.iv_consistency, which certified them):
- Black-76 on the implied forward, r = 0 (discounting negligible <= 35 DTE).
- Forward per minute from the ATM pair at the same timestamp: F = K + CE - PE.
  Fallback where the pair is missing: spot + that day's median basis; last
  resort F = spot.
- delta: forward delta, N(d1) for calls, N(d1) - 1 for puts.
- gamma: d(delta)/dF; vega per 1 vol-point; theta per calendar day (negative).
- Bars after the last detected expiry (dataset edge) get NaN greeks rather
  than a guessed tau.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import duckdb
from scipy.stats import norm

from . import config

ENRICHED_DIR = config.PARQUET_DIR / "options_enriched"
SETTLE_IST = "15:30"
TAU_FLOOR_S = 5 * 60          # floor for greek computation stability
SETTLE_WINDOW_S = 15 * 60     # flag bars this close to settlement


def load_calendar() -> dict[str, np.ndarray]:
    meta = duckdb.connect(str(config.META_DB), read_only=True)
    cal = meta.execute(
        "SELECT flag, expiry_date FROM expiry_calendar ORDER BY flag, expiry_date"
    ).fetchdf()
    meta.close()
    return {
        flag: pd.to_datetime(grp["expiry_date"]).dt.date.values
        for flag, grp in cal.groupby("flag")
    }


def _forward_per_ts(df: pd.DataFrame) -> pd.DataFrame:
    """Parity forward per timestamp from the ATM pair; day-median-basis fallback."""
    atm = df[df["strike_offset"] == 0].pivot_table(
        index="ts", columns="option_type", values=["close", "strike", "spot"],
        aggfunc="first",
    )
    atm.columns = ["_".join(c) for c in atm.columns]
    ok = atm.dropna(subset=["close_CE", "close_PE"])
    ok = ok[ok["strike_CE"] == ok["strike_PE"]]
    fwd = (ok["strike_CE"] + ok["close_CE"] - ok["close_PE"]).rename("fwd")

    out = df.merge(fwd, left_on="ts", right_index=True, how="left")
    # Fallback: day-median basis over spot, then plain spot.
    basis = (out["fwd"] - out["spot"]).groupby(out["d"]).transform("median")
    out["fwd"] = out["fwd"].fillna(out["spot"] + basis).fillna(out["spot"])
    return out


def enrich_frame(df: pd.DataFrame, flag: str, expiries: np.ndarray) -> pd.DataFrame:
    ist = df["ts"].dt.tz_convert("Asia/Kolkata")
    df = df.assign(d=ist.dt.date)
    df["special_session"] = ist.dt.hour >= 17  # Muhurat evening bars

    idx = np.searchsorted(expiries, df["d"].values, side="left")
    in_range = idx < len(expiries)
    df["expiry_date"] = pd.NaT
    df.loc[in_range, "expiry_date"] = pd.to_datetime(expiries[idx[in_range]])

    settle = (
        df["expiry_date"].dt.tz_localize("Asia/Kolkata")
        + pd.Timedelta(hours=15, minutes=30)
    )
    # Bar close (ts + 60s) is the observation time of `close`.
    tau_s = (settle - (df["ts"] + pd.Timedelta(seconds=60))).dt.total_seconds()
    df["settlement_window"] = tau_s <= SETTLE_WINDOW_S
    df["tau"] = np.maximum(tau_s, TAU_FLOOR_S) / (365.0 * 86400.0)
    df.loc[~in_range, "tau"] = np.nan

    df = _forward_per_ts(df)

    F, K = df["fwd"].values, df["strike"].values
    sigma = df["iv"].values / 100.0
    tau = df["tau"].values
    is_call = (df["option_type"] == "CE").values

    with np.errstate(all="ignore"):
        st = sigma * np.sqrt(tau)
        d1 = np.log(F / K) / st + 0.5 * st
        pdf1, cdf1 = norm.pdf(d1), norm.cdf(d1)
        df["delta"] = np.where(is_call, cdf1, cdf1 - 1.0)
        df["gamma"] = pdf1 / (F * st)
        df["vega"] = F * pdf1 * np.sqrt(tau) / 100.0
        df["theta_day"] = -(F * pdf1 * sigma) / (2.0 * np.sqrt(tau)) / 365.0

    bad = ~np.isfinite(st) | (st <= 0)
    df.loc[bad, ["delta", "gamma", "vega", "theta_day"]] = np.nan
    df["expiry_date"] = df["expiry_date"].dt.date
    return df.drop(columns=["d"])


def build() -> None:
    expiries = load_calendar()
    parts = sorted((config.PARQUET_DIR / "options").glob("flag=*/month=*/part.parquet"))
    n_rows = 0
    for path in parts:
        flag = path.parts[-3].split("=")[1]
        df = pd.read_parquet(path)
        out = enrich_frame(df, flag, expiries[flag])
        out = out.sort_values(["option_type", "strike_offset", "ts"])
        dest = ENRICHED_DIR / path.parts[-3] / path.parts[-2]
        dest.mkdir(parents=True, exist_ok=True)
        out.to_parquet(dest / "part.parquet", index=False)
        n_rows += len(out)
    print(f"enriched {n_rows:,} rows -> {ENRICHED_DIR}")
