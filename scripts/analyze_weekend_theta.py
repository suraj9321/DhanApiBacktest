#!/usr/bin/env python3
"""Analysis 2: weekend theta capture — the empirical verdict on Friday entries.

For each clean Fri->Mon pair (weekly front series): short the ATM straddle at
Friday 15:15, track the SAME strike to Monday 09:20 / Monday 15:15 / expiry
day 15:15. Compare realized capture against the pure-theta prediction
(Black-76 revalue with only tau reduced), attributing the shortfall to the
gap (gamma) and Monday IV re-markup (vega).

Strike matching: Monday's rows are searched for Friday's strike across all
offsets. If the weekend gap pushed the strike outside the ATM±10 window, exit
is approximated by intrinsic value (optimistic floor for a short) and the week
is reported separately in the `approx` bucket rather than silently mixed in.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402

Q = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
TIMES = ("15:15", "09:20")


def load_bars() -> pd.DataFrame:
    con = duckdb.connect()
    return con.execute(f"""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
               strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod,
               option_type, strike, close, iv, spot, fwd, tau, expiry_date
        FROM {Q}
        WHERE flag='week' AND NOT special_session
          AND strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') IN {TIMES}
    """).fetchdf()


def straddle_at(bars: pd.DataFrame, d, tod: str, strike: float):
    """(straddle_price, mean_iv, spot, fwd, tau) at a strike, or None."""
    rows = bars[(bars["d"] == d) & (bars["tod"] == tod) & (bars["strike"] == strike)]
    ce = rows[rows["option_type"] == "CE"]
    pe = rows[rows["option_type"] == "PE"]
    if len(ce) != 1 or len(pe) != 1:
        return None
    return (
        float(ce["close"].iloc[0] + pe["close"].iloc[0]),
        float((ce["iv"].iloc[0] + pe["iv"].iloc[0]) / 2),
        float(ce["spot"].iloc[0]),
        float(ce["fwd"].iloc[0]),
        float(ce["tau"].iloc[0]),
    )


def bs_straddle(F: float, K: float, sigma: float, tau: float) -> float:
    st = sigma * np.sqrt(tau)
    if st <= 0:
        return abs(F - K)
    d1 = np.log(F / K) / st + 0.5 * st
    d2 = d1 - st
    call = F * norm.cdf(d1) - K * norm.cdf(d2)
    put = K * norm.cdf(-d2) - F * norm.cdf(-d1)
    return float(call + put)


def main() -> None:
    bars = load_bars()
    dates = sorted(bars["d"].unique())
    nxt = {a: b for a, b in zip(dates, dates[1:])}

    rows = []
    for d in dates:
        if pd.Timestamp(d).weekday() != 4:  # Friday
            continue
        m = nxt.get(d)
        if m is None or pd.Timestamp(m).weekday() != 0 or (pd.Timestamp(m) - pd.Timestamp(d)).days != 3:
            continue
        # ATM at Friday 15:15 = strike of offset with min |strike - fwd|; use CE rows.
        fri = bars[(bars["d"] == d) & (bars["tod"] == "15:15") & (bars["option_type"] == "CE")]
        if fri.empty:
            continue
        K = float(fri.loc[(fri["strike"] - fri["fwd"]).abs().idxmin(), "strike"])
        e = straddle_at(bars, d, "15:15", K)
        if e is None:
            continue
        s_fri, iv_f, spot_f, fwd_f, tau_f = e
        expiry = fri["expiry_date"].iloc[0]

        gm = straddle_at(bars, m, "09:20", K)
        approx = gm is None
        spot_m_rows = bars[(bars["d"] == m) & (bars["tod"] == "09:20")]
        if spot_m_rows.empty:
            continue
        spot_m = float(spot_m_rows["spot"].iloc[0])
        if approx:
            s_mon, iv_m = abs(spot_m - K), np.nan  # intrinsic floor
        else:
            s_mon, iv_m = gm[0], gm[1]

        # Pure-theta prediction: only tau shrinks (2.6 calendar days), F & IV frozen.
        tau_m = tau_f - 2.6 / 365.0
        s_theta = bs_straddle(fwd_f, K, iv_f / 100.0, max(tau_m, 1e-6))

        m1515 = straddle_at(bars, m, "15:15", K)
        exp1515 = straddle_at(bars, expiry, "15:15", K) if expiry in nxt or expiry in dates else None

        rows.append({
            "friday": d, "expiry": expiry,
            "era": "Tue-expiry" if pd.Timestamp(expiry).weekday() == 1 else "Thu-expiry",
            "K": K, "entry": s_fri, "iv_fri": iv_f, "iv_mon": iv_m,
            "gap_pct": (spot_m / spot_f - 1) * 100,
            "wknd_pnl": s_fri - s_mon,               # short: entry - exit
            "theta_pred": s_fri - s_theta,
            "mon_pnl": (s_mon - m1515[0]) if m1515 else np.nan,
            "to_expiry_pnl": (s_fri - exp1515[0]) if exp1515 else np.nan,
            "approx": approx,
        })

    df = pd.DataFrame(rows)
    clean = df[~df["approx"]]

    print(f"weeks analyzed: {len(df)} (clean strike-match: {len(clean)}, "
          f"gap-outside-window approx: {df['approx'].sum()})")

    def seg(d_: pd.DataFrame, label: str) -> None:
        w = d_["wknd_pnl"]
        print(f"\n--- {label} (n={len(d_)}) ---")
        print(f"  entry straddle:      mean {d_['entry'].mean():7.1f} pts")
        print(f"  pure-theta pred:     mean {d_['theta_pred'].mean():7.1f} pts")
        print(f"  realized wknd pnl:   mean {w.mean():7.1f}  median {w.median():7.1f}  "
              f"sd {w.std():6.1f}  win% {100*(w>0).mean():5.1f}")
        print(f"  capture ratio:       {w.mean()/d_['theta_pred'].mean():5.2f} "
              f"(realized / pure-theta)")
        dl = d_.dropna(subset=["iv_mon"])
        print(f"  IV fri->mon:         {dl['iv_fri'].mean():5.2f} -> {dl['iv_mon'].mean():5.2f} "
              f"(re-markup {dl['iv_mon'].mean()-dl['iv_fri'].mean():+.2f} pts)")

    seg(clean, "ALL clean weeks")
    for era, grp in clean.groupby("era"):
        seg(grp, era)

    print("\n--- worst 8 weekends (incl. approx) ---")
    print(df.nsmallest(8, "wknd_pnl")[["friday", "era", "gap_pct", "entry", "wknd_pnl", "approx"]]
          .round(2).to_string(index=False))

    print("\n--- Monday session (same short structure continued), clean weeks ---")
    mp = clean["mon_pnl"].dropna()
    print(f"  mean {mp.mean():6.1f}  median {mp.median():6.1f}  win% {100*(mp>0).mean():5.1f}")

    meta = duckdb.connect("data/meta.duckdb")
    meta.execute("CREATE OR REPLACE TABLE analysis_weekend_theta AS SELECT * FROM df")
    meta.close()
    print("\nsaved: meta.duckdb::analysis_weekend_theta")


if __name__ == "__main__":
    main()
