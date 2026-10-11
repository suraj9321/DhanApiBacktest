"""Pivot + Supertrend momentum ATM option-selling backtest (intraday).

Strategy (from Suraj's screenshot, 2026-07-26):
  - Daily floor-trader pivots from the PREVIOUS day's H/L/C:
        PP = (H + L + C) / 3 ;  R1 = 2*PP - L ;  S1 = 2*PP - H
  - Supertrend(period=7, multiplier=3) on 5-minute candles defines the trend.
  - Trade fires only when price breaks a pivot IN THE TREND'S DIRECTION:
        Supertrend UP   and 5-min close > R1  -> SHORT the ATM PUT  (bullish)
        Supertrend DOWN and 5-min close < S1  -> SHORT the ATM CALL (bearish)
    Sell the ATM option of the front weekly expiry, collect premium.

Assumptions NOT specified in the screenshot (flagged for review):
  * One trade per day: first qualifying 5-min bar in the entry window triggers.
  * Entry window: first completed 5-min bar (09:20) .. 14:30 cutoff.
  * ATM = weekly-expiry strike nearest to spot at the signal bar.
  * Sizing: fixed 1 lot (75). P&L also expressed as % of Rs.8L capital.
  * Exit variants compared:
        - eod      : square off at 15:20 (pure baseline, no stop)
        - stop2x   : + cut the short if premium doubles (2x entry); else 15:20
        - flip     : + exit if Supertrend flips against the position; else 15:20
  * Supertrend computed CONTINUOUSLY across days (TradingView-style, Wilder ATR).
  * Costs via src/backtest/costs.py (2 orders/trade). Slippage 0.2% of premium.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent))
from src.backtest import costs
from src.backtest.data import MarketData

LOT_SIZE = 75
CAPITAL = 800_000.0
ST_PERIOD = 7
ST_MULT = 3.0
ENTRY_START = "09:20"
ENTRY_CUTOFF = "15:00"   # last entry (screenshot rule)
SQUAREOFF = "15:20"      # hard square-off
MAX_TRADES = 3           # per day (screenshot rule)


def five_min_bars() -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute("""
        SELECT ts AT TIME ZONE 'Asia/Kolkata' AS ts, open, high, low, close
        FROM read_parquet('data/parquet/spot/nifty_intraday/*/part.parquet')
        ORDER BY ts
    """).fetchdf()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")
    df["d"] = df.index.date
    # regular session only
    df = df.between_time("09:15", "15:29")
    out = []
    for d, g in df.groupby("d"):
        r = g.resample("5min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()
        r["d"] = d
        out.append(r)
    bars = pd.concat(out)
    # tod at which the bar COMPLETES (start + 5 min) -> the action timestamp
    bars["signal_tod"] = (bars.index + pd.Timedelta(minutes=5)).strftime("%H:%M")
    return bars


def supertrend(bars: pd.DataFrame, period: int, mult: float) -> pd.DataFrame:
    h, l, c = bars["high"].values, bars["low"].values, bars["close"].values
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    # Wilder / RMA ATR (TradingView default)
    atr = np.empty_like(tr)
    atr[0] = tr[0]
    alpha = 1.0 / period
    for i in range(1, len(tr)):
        atr[i] = atr[i - 1] + alpha * (tr[i] - atr[i - 1])
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    fu = upper.copy()
    fl = lower.copy()
    for i in range(1, len(c)):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
    direction = np.ones(len(c), dtype=int)  # 1 = up, -1 = down
    for i in range(1, len(c)):
        if c[i] > fu[i - 1]:
            direction[i] = 1
        elif c[i] < fl[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    bars = bars.copy()
    bars["st_dir"] = direction
    return bars


def daily_pivots() -> pd.DataFrame:
    con = duckdb.connect()
    d = con.execute("""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, high, low, close
        FROM read_parquet('data/parquet/spot/nifty_daily/*/part.parquet')
        ORDER BY ts
    """).fetchdf()
    d["pp"] = (d["high"] + d["low"] + d["close"]) / 3.0
    d["r1"] = 2 * d["pp"] - d["low"]
    d["s1"] = 2 * d["pp"] - d["high"]
    # shift so row d carries PREVIOUS day's pivots
    piv = d[["pp", "r1", "s1"]].shift(1)
    piv["d"] = pd.to_datetime(d["d"]).dt.date
    return piv.dropna().set_index("d")


def atm_strike(md: MarketData, d, tod: str, opt_type: str):
    chain = md.chain_at(d, tod)
    chain = chain[chain["option_type"] == opt_type]
    if chain.empty:
        return None, None
    spot = float(chain["spot"].iloc[0])
    row = chain.iloc[(chain["strike"] - spot).abs().argmin()]
    return float(row["strike"]), float(row["close"])


def _resolve_exit(bars, md, d, side, opt_type, strike, entry_prem, entry_tod, exit_mode):
    """Walk 5-min bars after entry; exit on Supertrend flip (or stop2x) else 15:20."""
    later = bars[(bars["d"] == d) & (bars["signal_tod"] > entry_tod)]
    for _, b2 in later.iterrows():
        t2 = b2["signal_tod"]
        if t2 > SQUAREOFF:
            break
        q = md.quote(d, t2, opt_type, strike)
        if q is None:
            continue
        if exit_mode == "stop2x" and q >= 2.0 * entry_prem:
            return q, t2, "stop_2x"
        flipped = (side == "bull" and b2["st_dir"] == -1) or (side == "bear" and b2["st_dir"] == 1)
        if exit_mode == "flip" and flipped:
            return q, t2, "st_flip"
        if t2 >= SQUAREOFF:
            return q, t2, "eod_squareoff"
    q = md.quote(d, SQUAREOFF, opt_type, strike)
    return (q, SQUAREOFF, "eod_squareoff") if q is not None else (None, None, None)


def run(bars, piv, md, exit_mode: str, start_date, end_date) -> pd.DataFrame:
    """Screenshot rules: up to MAX_TRADES/day, entry 09:20..15:00, re-entry after
    each exit; exit on Supertrend flip (exit_mode='flip') or hard square-off 15:20."""
    trades = []
    for d, g in bars.groupby("d"):
        if d < start_date or d > end_date or d not in piv.index or d not in md.calendar:
            continue
        p = piv.loc[d]
        window = g[(g["signal_tod"] >= ENTRY_START) & (g["signal_tod"] <= ENTRY_CUTOFF)]
        n_trades, last_exit = 0, "00:00"
        while n_trades < MAX_TRADES:
            sig = None
            for _, bar in window[window["signal_tod"] > last_exit].iterrows():
                if bar["st_dir"] == 1 and bar["close"] > p["r1"]:
                    sig = ("bull", "PE", bar); break
                if bar["st_dir"] == -1 and bar["close"] < p["s1"]:
                    sig = ("bear", "CE", bar); break
            if sig is None:
                break
            side, opt_type, bar = sig
            tod = bar["signal_tod"]
            strike, entry_prem = atm_strike(md, d, tod, opt_type)
            if strike is None or entry_prem is None or entry_prem <= 0:
                last_exit = tod
                continue
            exit_prem, exit_tod, reason = _resolve_exit(
                bars, md, d, side, opt_type, strike, entry_prem, tod, exit_mode)
            if exit_prem is None:
                break

            units = LOT_SIZE
            sell = costs.execute(is_buy=False, mid_price=entry_prem, units=units)   # short entry
            buy = costs.execute(is_buy=True, mid_price=exit_prem, units=units)      # cover
            gross = (sell.fill_price - buy.fill_price) * units   # slippage already in fills
            pnl = gross - (sell.charges + buy.charges)
            trades.append({
                "d": d, "side": side, "opt": opt_type, "strike": strike,
                "entry_tod": tod, "entry_prem": entry_prem, "exit_tod": exit_tod,
                "exit_prem": exit_prem, "reason": reason,
                "gross": gross, "charges": sell.charges + buy.charges,
                "slippage": sell.slippage_rupees + buy.slippage_rupees, "pnl": pnl,
            })
            n_trades += 1
            last_exit = exit_tod
    return pd.DataFrame(trades)


def summarize(name, tr: pd.DataFrame):
    if tr.empty:
        print(f"\n=== {name} ===  no trades")
        return
    pnl = tr["pnl"]
    total = pnl.sum()
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    eq = CAPITAL + pnl.cumsum()
    peak = eq.cummax()
    maxdd = ((eq - peak) / peak).min() * 100
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf
    daily_ret = pnl / CAPITAL
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else np.nan
    print(f"\n=== {name} ===")
    print(f"  trades              {len(tr)}")
    print(f"  net P&L (Rs)        {total:,.0f}")
    print(f"  return on 8L        {100*total/CAPITAL:+.2f}%")
    print(f"  win rate            {100*(pnl>0).mean():.1f}%")
    print(f"  avg win / avg loss  {wins.mean():,.0f} / {losses.mean() if len(losses) else 0:,.0f}")
    print(f"  profit factor       {pf:.2f}")
    print(f"  worst trade         {pnl.min():,.0f}")
    print(f"  best trade          {pnl.max():,.0f}")
    print(f"  max drawdown        {maxdd:.2f}%")
    print(f"  sharpe (daily->ann) {sharpe:.2f}")
    print(f"  gross / costs       {tr['gross'].sum():,.0f} / {(tr['charges']+tr['slippage']).sum():,.0f}")
    print(f"  bull(PE) / bear(CE) {int((tr['side']=='bull').sum())} / {int((tr['side']=='bear').sum())}")
    print(f"  side P&L bull/bear  {tr[tr.side=='bull'].pnl.sum():,.0f} / {tr[tr.side=='bear'].pnl.sum():,.0f}")
    print(f"  exit reasons        {tr['reason'].value_counts().to_dict()}")


def main():
    print("Building 5-min bars + Supertrend + pivots ...")
    bars = supertrend(five_min_bars(), ST_PERIOD, ST_MULT)
    piv = daily_pivots()
    md = MarketData(flag="week")

    end_date = pd.Timestamp("2026-07-16").date()
    # Tuesday weekly-expiry regime: first day whose FRONT weekly expires on Tue
    # (2025-09-02) is Fri 2025-08-29. Confirmed empirically from expiry_date data.
    start_date = pd.Timestamp("2025-08-29").date()
    print(f"Window: {start_date} .. {end_date} (Tuesday weekly-expiry regime only)")
    print("Rules: exit=Supertrend flip OR hard square-off 15:20; max 3 trades/day; entry cutoff 15:00\n")

    tr = run(bars, piv, md, "flip", start_date, end_date)
    summarize("pivot+supertrend (Tue-regime, flip/squareoff, 3/day)", tr)

    # For contrast only: the prior Thursday-expiry era under identical rules.
    print("\n\n########## CONTEXT: prior Thursday-expiry era (2021 .. 2025-08-28) ##########")
    thu = run(bars, piv, md, "flip", pd.Timestamp("2021-01-01").date(),
              pd.Timestamp("2025-08-28").date())
    if not thu.empty:
        print(f"  trades {len(thu)}  netP&L {thu['pnl'].sum():,.0f}  "
              f"ret {100*thu['pnl'].sum()/CAPITAL:+.2f}%  win {100*(thu['pnl']>0).mean():.0f}%  "
              f"PF {thu['pnl'][thu.pnl>0].sum()/-thu['pnl'][thu.pnl<=0].sum():.2f}")

    out = Path("data/backtest_pivot_supertrend_trades.parquet")
    tr.to_parquet(out)
    print(f"\nSaved Tue-regime trades -> {out}")
    print(f"Quote fallbacks: {md.fallback_counts}")


if __name__ == "__main__":
    main()
