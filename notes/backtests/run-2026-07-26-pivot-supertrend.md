# Pivot + Supertrend momentum ATM option-selling — 2026-07-26

Source: Suraj's screenshot (a directional intraday premium-selling idea, distinct
from the VRP/range family). Engine: `scripts/run_pivot_supertrend.py` (standalone
intraday flow; reuses `src/backtest/costs.py` and `MarketData(flag='week')`).

## Rules
- Daily floor-trader pivots from **previous** day H/L/C: `PP=(H+L+C)/3`,
  `R1=2PP−L`, `S1=2PP−H`.
- **Supertrend(7,3)** on 5-min candles, computed continuously (Wilder ATR, TV-style).
- Entry (in trend direction only), first qualifying 5-min bar 09:20–14:30, 1/day:
  - ST up   & 5-min close > R1 → **short ATM PE** (front weekly)
  - ST down & 5-min close < S1 → **short ATM CE**
- ATM = weekly strike nearest spot at signal bar. Fixed **1 lot (75)**. Capital ₹8L.
- Exit variants: `eod` (square off 15:20, baseline), `stop2x` (cut if premium 2×),
  `flip` (exit on Supertrend flip). Costs: 2 orders/trade, slippage 0.2% premium.

## Assumptions flagged (NOT in the screenshot — biggest levers)
One-trade-per-day, entry window/cutoff, and **exit rule** are all my defaults; the
screenshot specifies entries only. Naked (no protective wing) — pure form of the idea.

## Result — last 1 year (2025-07-17 → 2026-07-16)

| exit    | net ₹   | ret/8L | win% | PF   | maxDD  | Sharpe | worst  |
|---------|---------|--------|------|------|--------|--------|--------|
| eod     | +21,029 | +2.63% | 65.1 | 1.06 | −7.59% | 0.35   | −24,163|
| stop2x  | −9,298  | −1.16% | 62.6 | 0.97 | −9.10% | −0.16  | −17,626|
| flip    | +13,042 | +1.63% | 54.9 | 1.06 | −7.93% | 0.33   | −10,884|

195 trades (~1/day). **Edge is not real:** PF 1.06, costs (₹19.2k) = 57% of gross
(₹33.4k); avg loss (−5.0k) ≫ avg win (2.9k) — classic short-gamma payoff. Entire
profit is the **CE/bear side (+35,035); the PE/bull side LOST (−14,005)**. A stop-loss
makes it *worse* (crystallises gamma losses) — telltale that "edge" is just being
short gamma, not the signal.

## Yearly context (baseline eod, full history) — 4 of 6 years NEGATIVE
```
2021 +5.50%   2022 −7.92%   2023 −2.25%   2024 −4.08%   2025 +1.18%   2026 −0.43% (YTD)
```
The +2.63% last-year figure is one of the better years and still razor-thin with a
−7.6% intra-year drawdown. Not robust; consistent with the expiry-day-condor and naked
range-strangle findings — underwriting intraday direction without a genuine VRP gate or
a hedge doesn't clear costs.

Trades saved: `data/backtest_pivot_supertrend_trades.parquet`.
