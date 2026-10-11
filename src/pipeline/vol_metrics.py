"""Vol-metrics library: realized-vol forecasts, IV series, and the VRP signal.

Design (see notes/vol-metrics.md):
- RV estimators: close-to-close rolling, EWMA(0.94), GARCH(1,1) with expanding
  yearly refits (parameters fitted only on data before each year — no
  look-ahead), HAR-RV on 5-minute realized variance + overnight gap^2.
- IV: single parity-consistent ATM IV inverted from the straddle price
  (Black-76 on the implied forward) — immune to the vendor's same-strike
  CE/PE IV asymmetry. Sampled 15:15 (signal close) and 09:20 (entry morning).
- Constant-maturity 7d/30d IVs by linear interpolation in total variance
  (kills the expiry sawtooth).
- Output: one row per trading day in data/parquet/signals/daily_signals.parquet
  and meta.duckdb::daily_signals. Columns suffixed _fwd are look-ahead and
  exist ONLY for forecast evaluation — never for signal generation.

All vols are annualized (252) and quoted in percent (e.g. 14.2).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import duckdb
from arch import arch_model
from scipy.optimize import brentq
from scipy.stats import norm

from . import config

DAILY = "read_parquet('data/parquet/spot/nifty_daily/*/*.parquet')"
INTRA = "read_parquet('data/parquet/spot/nifty_intraday/*/*.parquet')"
VIX = "read_parquet('data/parquet/spot/indiavix_daily/*/*.parquet')"
OPT = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
SIGNALS_PATH = config.PARQUET_DIR / "signals" / "daily_signals.parquet"
ANN = 252


# ---------- spot & realized vol ----------

def load_daily_spot(con) -> pd.DataFrame:
    df = con.execute(f"""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, open, close
        FROM {DAILY}
        WHERE dayname(CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE)) NOT IN ('Saturday','Sunday')
        ORDER BY d
    """).fetchdf()
    df["ret_cc"] = np.log(df["close"] / df["close"].shift(1))
    df["ret_on"] = np.log(df["open"] / df["close"].shift(1))  # overnight gap
    return df.dropna(subset=["ret_cc"]).reset_index(drop=True)


def intraday_rv(con) -> pd.DataFrame:
    """Daily realized variance from 5-min returns (2021+), intraday only."""
    df = con.execute(f"""
        WITH m AS (
          SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, ts, close,
                 minute(ts AT TIME ZONE 'Asia/Kolkata') AS minu,
                 hour(ts AT TIME ZONE 'Asia/Kolkata') AS h
          FROM {INTRA}
          WHERE dayname(CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE)) NOT IN ('Saturday','Sunday')
            AND hour(ts AT TIME ZONE 'Asia/Kolkata') < 16
        )
        SELECT d, ts, close FROM m WHERE minu % 5 = 0 ORDER BY ts
    """).fetchdf()
    df["r"] = np.log(df["close"] / df["close"].shift(1))
    first = df.groupby("d")["ts"].transform("min")
    df.loc[df["ts"] == first, "r"] = np.nan  # drop cross-session return
    rv = df.groupby("d")["r"].apply(lambda s: float(np.nansum(s * s))).rename("rv_intra")
    return rv.reset_index()


def ewma_vol(ret: pd.Series, lam: float = 0.94) -> pd.Series:
    var = np.empty(len(ret))
    var[0] = ret.iloc[:60].var()
    r2 = (ret ** 2).values
    for i in range(1, len(ret)):
        var[i] = lam * var[i - 1] + (1 - lam) * r2[i]
    return pd.Series(np.sqrt(var * ANN) * 100, index=ret.index)


def garch_vol(dates: pd.Series, ret: pd.Series, first_year: int = 2012) -> pd.Series:
    """1-step-ahead GARCH(1,1) vol; parameters refit each Jan on prior data only."""
    r = ret.values * 100
    years = pd.to_datetime(dates).dt.year.values
    out = np.full(len(r), np.nan)
    for year in range(first_year, years.max() + 1):
        fit_mask = years < year
        if fit_mask.sum() < 750:
            continue
        res = arch_model(r[fit_mask], vol="GARCH", p=1, q=1, mean="Zero").fit(disp="off")
        omega, alpha, beta = (res.params[k] for k in ("omega", "alpha[1]", "beta[1]"))
        # Filter the whole history with fixed params; write this year's values.
        sigma2 = np.empty(len(r))
        sigma2[0] = np.var(r[:250])
        for i in range(1, len(r)):
            sigma2[i] = omega + alpha * r[i - 1] ** 2 + beta * sigma2[i - 1]
        year_mask = years == year
        out[year_mask] = np.sqrt(sigma2[year_mask] * ANN) / 100 * 100
    return pd.Series(out, index=ret.index)


def har_forecast(rv: pd.DataFrame, min_obs: int = 200) -> pd.Series:
    """Forecast next-5-session mean daily variance; quarterly expanding refits.

    rv: columns d, rv_total (daily variance incl. overnight^2). Returns
    annualized vol forecast indexed like rv.
    """
    v = np.log(np.clip(rv["rv_total"].values, 1e-10, None))
    y = pd.Series(v).shift(-1).rolling(5).mean().shift(-4).values  # mean log-var t+1..t+5
    x_d = v
    x_w = pd.Series(v).rolling(5).mean().values
    x_m = pd.Series(v).rolling(22).mean().values
    dates = pd.to_datetime(rv["d"])
    quarter = dates.dt.year * 10 + dates.dt.quarter
    out = np.full(len(v), np.nan)
    for q in sorted(quarter.unique()):
        train = (quarter < q).values & ~np.isnan(y) & ~np.isnan(x_m)
        if train.sum() < min_obs:
            continue
        X = np.column_stack([np.ones(train.sum()), x_d[train], x_w[train], x_m[train]])
        coef, *_ = np.linalg.lstsq(X, y[train], rcond=None)
        resid_var = np.var(y[train] - X @ coef)
        pred_mask = (quarter == q).values & ~np.isnan(x_m)
        Xp = np.column_stack([np.ones(pred_mask.sum()), x_d[pred_mask], x_w[pred_mask], x_m[pred_mask]])
        # exp of log-forecast needs the half-variance correction to be unbiased
        out[pred_mask] = np.exp(Xp @ coef + 0.5 * resid_var)
    return pd.Series(np.sqrt(out * ANN) * 100, index=rv.index)


# ---------- implied vol ----------

def _b76_straddle(F: float, K: float, tau: float, sigma: float) -> float:
    st = sigma * np.sqrt(tau)
    d1 = np.log(F / K) / st + 0.5 * st
    d2 = d1 - st
    return F * (norm.cdf(d1) - norm.cdf(-d1)) - K * (norm.cdf(d2) - norm.cdf(-d2))


def implied_vol(price: float, F: float, K: float, tau: float) -> float:
    intrinsic = abs(F - K)
    if tau <= 0 or price <= intrinsic + 1e-6:
        return np.nan
    try:
        return brentq(lambda s: _b76_straddle(F, K, tau, s) - price, 1e-3, 3.0, xtol=1e-6)
    except ValueError:
        return np.nan


def atm_iv_table(con) -> pd.DataFrame:
    """Per day: parity-consistent ATM straddle IV per (flag, tod) + tau."""
    df = con.execute(f"""
        WITH atm AS (
          SELECT flag, CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
                 strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod,
                 option_type, close, strike, fwd, tau
          FROM {OPT}
          WHERE strike_offset = 0 AND NOT special_session AND NOT settlement_window
            AND expiry_date IS NOT NULL AND tau > 0.0015  -- > ~half day: no dying-contract IVs
            AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') IN ('09:20','15:15')
        )
        SELECT ce.flag, ce.d, ce.tod, ce.strike, ce.fwd, ce.tau,
               ce.close + pe.close AS straddle
        FROM (SELECT * FROM atm WHERE option_type='CE') ce
        JOIN (SELECT * FROM atm WHERE option_type='PE') pe
          USING (flag, d, tod, strike)
    """).fetchdf()
    df["iv"] = [
        implied_vol(p, f, k, t) * 100 if np.isfinite(t) else np.nan
        for p, f, k, t in zip(df["straddle"], df["fwd"], df["strike"], df["tau"])
    ]
    piv = df.pivot_table(index="d", columns=["flag", "tod"], values=["iv", "tau"], aggfunc="first")
    piv.columns = [f"{a}_{f}_{t.replace(':', '')}" for a, f, t in piv.columns]
    return piv.reset_index()


def constant_maturity(iv_w, tau_w, iv_m, tau_m, target_days: float) -> pd.Series:
    """Interpolate total variance to a fixed horizon; clamp outside the span."""
    tgt = target_days / 365.0
    vw, vm = (iv_w / 100) ** 2 * tau_w, (iv_m / 100) ** 2 * tau_m
    w = ((tgt - tau_w) / (tau_m - tau_w)).clip(0, 1)
    var = vw + w * (vm - vw)
    tau_eff = tau_w + w * (tau_m - tau_w)
    return np.sqrt(var / tau_eff) * 100


# ---------- assembly ----------

def build_signals() -> pd.DataFrame:
    con = duckdb.connect()
    spot = load_daily_spot(con)
    rv_i = intraday_rv(con)

    spot = spot.merge(rv_i, on="d", how="left")
    spot["rv_total"] = spot["rv_intra"] + spot["ret_on"] ** 2
    spot["rv_cc21"] = spot["ret_cc"].rolling(21).std() * np.sqrt(ANN) * 100
    spot["rv_ewma"] = ewma_vol(spot["ret_cc"])
    spot["rv_garch"] = garch_vol(spot["d"], spot["ret_cc"])

    har_in = spot.dropna(subset=["rv_total"])[["d", "rv_total"]].reset_index(drop=True)
    har = har_forecast(har_in)
    spot = spot.merge(pd.DataFrame({"d": har_in["d"], "rv_har5": har.values}), on="d", how="left")

    # Realized future vol (evaluation only).
    fwd_var = pd.Series(spot["rv_total"].values).shift(-1).rolling(5).mean().shift(-4)
    spot["rv_fwd5_EVAL"] = np.sqrt(fwd_var * ANN) * 100

    iv = atm_iv_table(con)
    vix = con.execute(f"""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, close AS vix
        FROM {VIX} WHERE close > 0
    """).fetchdf()

    sig = spot.merge(iv, on="d", how="left").merge(vix, on="d", how="left")
    sig["cm7_iv"] = constant_maturity(sig["iv_week_1515"], sig["tau_week_1515"],
                                      sig["iv_month_1515"], sig["tau_month_1515"], 7)
    sig["cm30_iv"] = constant_maturity(sig["iv_week_1515"], sig["tau_week_1515"],
                                       sig["iv_month_1515"], sig["tau_month_1515"], 30)
    sig["term_slope"] = sig["cm30_iv"] - sig["cm7_iv"]

    # Expiry days have no usable weekly IV; fall back to monthly (flat extrapolation).
    sig["cm7_iv"] = sig["cm7_iv"].fillna(sig["iv_month_1515"])
    sig["rv_blend"] = sig["rv_har5"].fillna(sig["rv_ewma"])
    sig["vrp_week"] = sig["cm7_iv"] - sig["rv_blend"]      # horizon-matched: 7d IV vs 5-session RV forecast
    sig["vrp_month"] = sig["cm30_iv"] - sig["rv_blend"]
    roll = sig["vrp_week"].rolling(252, min_periods=100)
    sig["vrp_z"] = (sig["vrp_week"] - roll.mean()) / roll.std()
    sig["iv_rank_1y"] = sig["cm7_iv"].rolling(252, min_periods=100).rank(pct=True) * 100

    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    sig.to_parquet(SIGNALS_PATH, index=False)
    meta = duckdb.connect(str(config.META_DB))
    meta.execute("CREATE OR REPLACE TABLE daily_signals AS SELECT * FROM sig")
    meta.close()
    return sig
