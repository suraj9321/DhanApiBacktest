#!/usr/bin/env python3
"""Analysis: the user's proposed window — enter T-1 09:20, exit expiry ~13:15
or at profit target, whichever first. Era-agnostic (T-1 = Monday in the
Tuesday-expiry regime, Wednesday in the Thursday regime), so all ~250 weekly
cycles contribute.

Structures: short ATM straddle; short ~15-delta strangle (legs chosen by
enriched delta at entry). Exits: none (hold to expiry 13:15), 50% and 70% of
credit captured, checked minute by minute. Missing far-OTM minutes are
forward-filled; the position is valued leg by leg at fixed strikes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

Q = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
ENTRY_TOD = "09:20"
EXIT_TOD = "13:15"
TARGETS = [None, 0.5, 0.7]


def load() -> pd.DataFrame:
    con = duckdb.connect()
    return con.execute(f"""
        WITH sess AS (
          SELECT expiry_date, d, row_number() OVER (PARTITION BY expiry_date ORDER BY d DESC) - 1 AS idx
          FROM (SELECT DISTINCT expiry_date, CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d
                FROM {Q} WHERE flag='week' AND expiry_date IS NOT NULL AND NOT special_session)
        )
        SELECT b.expiry_date, CAST(b.ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
               strftime(b.ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod,
               b.ts, b.option_type, b.strike, b.close, b.spot, b.delta, s.idx
        FROM {Q} b
        JOIN sess s ON s.expiry_date = b.expiry_date
                   AND s.d = CAST(b.ts AT TIME ZONE 'Asia/Kolkata' AS DATE)
        WHERE b.flag='week' AND s.idx <= 1 AND NOT b.special_session
    """).fetchdf()


def leg_path(cyc: pd.DataFrame, opt: str, strike: float) -> pd.Series:
    p = (cyc[(cyc["option_type"] == opt) & (cyc["strike"] == strike)]
         .set_index("ts")["close"].sort_index())
    return p


def run_cycle(cyc: pd.DataFrame, expiry) -> dict | None:
    entry_rows = cyc[(cyc["idx"] == 1) & (cyc["tod"] == ENTRY_TOD)]
    if entry_rows.empty:
        return None
    spot0 = entry_rows["spot"].iloc[0]

    # ATM strike at entry; 15-delta legs by enriched delta.
    ce = entry_rows[entry_rows["option_type"] == "CE"]
    pe = entry_rows[entry_rows["option_type"] == "PE"]
    if ce.empty or pe.empty:
        return None
    k_atm = ce.loc[(ce["strike"] - spot0).abs().idxmin(), "strike"]
    ce_ok = ce.dropna(subset=["delta"])
    pe_ok = pe.dropna(subset=["delta"])
    if ce_ok.empty or pe_ok.empty:
        return None
    k_ce15 = ce_ok.loc[(ce_ok["delta"] - 0.15).abs().idxmin(), "strike"]
    k_pe15 = pe_ok.loc[(pe_ok["delta"] + 0.15).abs().idxmin(), "strike"]

    out = {"expiry": expiry, "era": "Tue" if pd.Timestamp(expiry).weekday() == 1 else "Thu"}
    exit_cut = cyc[(cyc["idx"] == 0) & (cyc["tod"] == EXIT_TOD)]["ts"]
    if exit_cut.empty:
        return None
    t_end = exit_cut.iloc[0]

    for name, legs in (("straddle", [("CE", k_atm), ("PE", k_atm)]),
                       ("strangle15", [("CE", k_ce15), ("PE", k_pe15)])):
        paths = [leg_path(cyc, o, k) for o, k in legs]
        idx = paths[0].index.union(paths[1].index)
        idx = idx[(idx >= entry_rows["ts"].iloc[0]) & (idx <= t_end)]
        v = sum(p.reindex(idx).ffill() for p in paths).dropna()
        if v.empty or v.index[0] != entry_rows["ts"].iloc[0]:
            return None
        c0 = v.iloc[0]
        for tgt in TARGETS:
            key = f"{name}_{'hold' if tgt is None else int(tgt*100)}"
            if tgt is None:
                pnl, hit, t_exit = c0 - v.iloc[-1], False, v.index[-1]
            else:
                below = v[v <= c0 * (1 - tgt)]
                if len(below):
                    pnl, hit, t_exit = c0 - below.iloc[0], True, below.index[0]
                else:
                    pnl, hit, t_exit = c0 - v.iloc[-1], False, v.index[-1]
            out[f"{key}_pnl"] = pnl
            out[f"{key}_pnl_pct"] = pnl / c0 * 100
            out[f"{key}_hit"] = hit
        out[f"{name}_credit"] = c0
        out[f"{name}_credit_pct_spot"] = c0 / spot0 * 100
    return out


def main() -> None:
    bars = load()
    rows = []
    for expiry, cyc in bars.groupby("expiry_date"):
        r = run_cycle(cyc, expiry)
        if r:
            rows.append(r)
    df = pd.DataFrame(rows)
    print(f"cycles: {len(df)}  (Thu-era {sum(df['era']=='Thu')}, Tue-era {sum(df['era']=='Tue')})")

    for name in ("straddle", "strangle15"):
        print(f"\n=== short {name}: T-1 {ENTRY_TOD} -> expiry {EXIT_TOD} "
              f"(mean credit {df[f'{name}_credit'].mean():.0f} pts = "
              f"{df[f'{name}_credit_pct_spot'].mean():.2f}% spot) ===")
        for tgt in TARGETS:
            key = f"{name}_{'hold' if tgt is None else int(tgt*100)}"
            p, ppct = df[f"{key}_pnl"], df[f"{key}_pnl_pct"]
            line = (f"  {'no target (hold)' if tgt is None else f'{int(tgt*100)}% target':>18}: "
                    f"mean {p.mean():6.1f} pts ({ppct.mean():5.1f}% of credit)  "
                    f"median {p.median():6.1f}  win% {100*(p>0).mean():4.1f}  "
                    f"sd {p.std():5.1f}  worst {p.min():7.1f}")
            if tgt is not None:
                line += f"  target-hit {100*df[f'{key}_hit'].mean():.0f}%"
            print(line)
        w = df.nsmallest(5, f"{name}_hold_pnl")[["expiry", "era", f"{name}_hold_pnl"]]
        print("  worst 5 (hold): " + ", ".join(
            f"{str(r['expiry'])[:10]} {r[f'{name}_hold_pnl']:.0f}" for _, r in w.iterrows()))

    meta = duckdb.connect("data/meta.duckdb")
    meta.execute("CREATE OR REPLACE TABLE analysis_monday_entry AS SELECT * FROM df")
    meta.close()
    print("\nsaved: meta.duckdb::analysis_monday_entry")


if __name__ == "__main__":
    main()
