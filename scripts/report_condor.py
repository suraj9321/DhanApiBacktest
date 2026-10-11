#!/usr/bin/env python3
"""HTML dashboard for the MAIN condor/fly engine ledger (scripts/run_backtest.py).

The main engine writes a two-row event log (entry/exit) with per-trade `charges`
and `slippage`; this flattens it to the one-row-per-trade schema that
`backtest_report.build_html` expects, nets charges out of P&L so totals match the
CLI metrics, and classifies each (market-neutral) trade by the realised Nifty move
over the hold so the "by direction" panel is meaningful.

    python scripts/report_condor.py data/backtest_<name>_trades.parquet "<Title>" [out.html]

Alt-runner ledgers that are already flat should use backtest_report.py directly.
"""
from __future__ import annotations

import ast
import glob
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_report import build_html  # noqa: E402

CAPITAL = 800_000.0
DIR_BAND = 0.003  # ±0.3% close-to-close → bullish / bearish, else neutral


def _nifty_close() -> pd.Series:
    files = sorted(glob.glob("data/parquet/spot/nifty_daily/**/*.parquet", recursive=True))
    df = pd.read_parquet(files)
    df["d"] = pd.to_datetime(df["ts"]).dt.tz_convert("Asia/Kolkata").dt.normalize().dt.tz_localize(None)
    return df.set_index("d")["close"].sort_index()


def _nearest_close(close: pd.Series, d: pd.Timestamp) -> float | None:
    sub = close[close.index <= d]
    return float(sub.iloc[-1]) if len(sub) else None


def flatten(path: str) -> pd.DataFrame:
    tr = pd.read_parquet(path)
    tr["d"] = pd.to_datetime(tr["d"])
    entries = tr[tr["event"] == "entry"].reset_index(drop=True)
    exits = tr[tr["event"] == "exit"].reset_index(drop=True)
    n = min(len(entries), len(exits))  # engine is flat-between-trades, so rows pair 1:1
    close = _nifty_close()
    rows = []
    for i in range(n):
        en, ex = entries.iloc[i], exits.iloc[i]
        strikes = ast.literal_eval(en["strikes"]) if isinstance(en["strikes"], str) else {}
        pnl_gross = float(ex["pnl_gross"])
        charges = float(ex.get("charges", 0.0) or 0.0)
        slippage = float(ex.get("slippage", 0.0) or 0.0)
        c0, c1 = _nearest_close(close, en["d"]), _nearest_close(close, ex["d"])
        move = (c1 - c0) / c0 if (c0 and c1) else 0.0
        direction = "bullish" if move > DIR_BAND else "bearish" if move < -DIR_BAND else "neutral"
        rows.append({
            "d": en["d"],
            "pnl": pnl_gross - charges,            # net of statutory charges → matches equity
            "gross": pnl_gross + slippage,         # before all costs (slippage already in pnl_gross)
            "charges": charges, "slippage": slippage,
            "direction": direction,
            "short_put": strikes.get("PE", 0.0), "short_call": strikes.get("CE", 0.0),
            "credit_pts": float(en.get("credit", 0.0) or 0.0),
            "entry_tod": en.get("tod", ""), "exit_tod": ex.get("tod", ""),
            "reason": ex.get("reason", ""),
        })
    return pd.DataFrame(rows)


def main() -> None:
    path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else Path(path).stem
    out = sys.argv[3] if len(sys.argv) > 3 else path.replace("_trades.parquet", "_report.html")
    tr = flatten(path)
    with open(out, "w") as f:
        f.write(build_html(tr, title, CAPITAL))
    print(f"Wrote {out}  ({len(tr)} trades, net ₹{tr['pnl'].sum():,.0f})")


if __name__ == "__main__":
    main()
