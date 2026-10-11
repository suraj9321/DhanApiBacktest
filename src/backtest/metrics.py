"""Performance metrics from the equity curve and trade ledger."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute(result: dict, capital: float) -> dict:
    eq = result["equity"].copy()
    trades = result["trades"]
    out = {}
    if eq.empty:
        return {"error": "no equity rows"}
    eq["ret"] = eq["equity"].pct_change()
    n_days = len(eq)
    years = n_days / 252
    total_ret = eq["equity"].iloc[-1] / capital - 1
    out["final_equity"] = float(eq["equity"].iloc[-1])
    out["total_return_pct"] = 100 * total_ret
    out["cagr_pct"] = 100 * ((1 + total_ret) ** (1 / years) - 1) if years > 0.2 else np.nan
    daily = eq["ret"].dropna()
    out["ann_vol_pct"] = 100 * daily.std() * np.sqrt(252)
    out["sharpe"] = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan
    peak = eq["equity"].cummax()
    out["max_dd_pct"] = 100 * ((eq["equity"] - peak) / peak).min()

    exits = trades[trades["event"] == "exit"] if len(trades) else pd.DataFrame()
    if len(exits):
        pnl = exits["pnl_gross"]
        out["n_trades"] = len(exits)
        out["win_rate_pct"] = 100 * (pnl > 0).mean()
        out["avg_win"] = float(pnl[pnl > 0].mean()) if (pnl > 0).any() else 0.0
        out["avg_loss"] = float(pnl[pnl <= 0].mean()) if (pnl <= 0).any() else 0.0
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = -pnl[pnl <= 0].sum()
        out["profit_factor"] = float(gross_profit / gross_loss) if gross_loss > 0 else np.inf
        out["worst_trade"] = float(pnl.min())
        out["exit_reasons"] = exits["reason"].value_counts().to_dict()
        gross_total = pnl[pnl > 0].sum()
        costs = result["charges_total"] + result["slippage_total"]
        out["costs_total"] = float(costs)
        out["costs_pct_of_gross_wins"] = 100 * costs / gross_total if gross_total > 0 else np.nan
    out["risk_events"] = result["risk_events"]
    out["quote_fallbacks"] = result["fallbacks"]
    return out


def print_report(name: str, m: dict) -> None:
    print(f"\n=== {name} ===")
    for k in ("final_equity", "total_return_pct", "cagr_pct", "ann_vol_pct", "sharpe",
              "max_dd_pct", "n_trades", "win_rate_pct", "avg_win", "avg_loss",
              "profit_factor", "worst_trade", "costs_total", "costs_pct_of_gross_wins"):
        if k in m:
            v = m[k]
            print(f"  {k:26s} {v:,.2f}" if isinstance(v, (int, float)) and np.isfinite(v)
                  else f"  {k:26s} {v}")
    for k in ("exit_reasons", "risk_events", "quote_fallbacks"):
        if m.get(k):
            print(f"  {k:26s} {m[k]}")
