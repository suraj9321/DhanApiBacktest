---
tags: [backtest, log]
date: 2026-07-18
---

# Backtest series: iron fly variants — first green run

Part of [[Home]] · follows [[run-2026-07-18-weekly-v01]] · configs `weekly_fly*.yaml` · ledgers `data/backtest_weekly_fly*_*.parquet`.

## The three runs

| Run | Gate | Net 5y | Sharpe | MaxDD | Trades | Win% | PF | Costs/gross wins |
|---|---|---|---|---|---|---|---|---|
| weekly_fly | vrp>0 only | −10.7% | −0.34 | −17.0% | 210 | 54% | 0.94 | 20% |
| weekly_fly_z05 | vrp_z ≥ 0.5 | −15.0% | −0.69 | −17.5% | 69 | 39% | 0.65 | 25% |
| **weekly_fly_zband** | **vrp>0 AND z ≤ 0.5** | **+6.7%** | **0.40** | **−4.5%** | 123 | 64% | 1.31 | **10.6%** |

*(zband run also includes the slippage recalibration below — both changes contributed.)*

## Finding 1: the VRP-gate inversion (scientifically important)

Bucket attribution of the unconditional fly's 210 trades by entry-day `vrp_z`:

| z bucket | n | mean P&L | win% |
|---|---|---|---|
| z < −0.5 | 19 | +465 | 63 |
| −0.5..0 | 46 | +65 | 59 |
| 0..0.5 | 58 | **+886** | 66 |
| 0.5..1 | 31 | **−2,609** | 42 |
| > 1 | 38 | −570 | 37 |

**"Sell when VRP is unusually wide" is backwards for the weekly gamma trade.** An abnormally wide measured VRP is a *stress signature*: IV rises faster than lagging RV forecasts precisely when realized vol is about to overshoot. The correct gate: **premium must exist (vrp>0) but must NOT be a stress outlier (z ≤ 0.5)**. Same story in iv_rank: top-quartile weeks lose (win 41%). → [[vrp-signals]] Tier-1 corrected accordingly.

## Finding 2: wings' carry cost ≈ the unconditional edge

The unconditional fly grossed only ~+₹27k/5y vs the straddle's measured +16 pts/wk ([[analysis-monday-entry]]): the wings' time-value decay over the holding window consumes almost the entire unconditional edge. Insurance costs ≈ premium edge → only *selected* weeks are worth trading. The gate is not an enhancement; it is the strategy.

## Finding 3: slippage model recalibrated

Original 0.8%-of-premium half-spread overtaxed deep-liquid ATM legs several-fold (real Nifty weekly ATM spreads ~0.1–0.2%). Now 0.2% (floor 0.05, cap 0.75 pts) — **must be calibrated against live order books before real money** (flag carried in `costs.py`).

## Mandatory caveats on the green run

1. **In-sample gate selection:** the z ≤ 0.5 rule was derived from these same 210 trades, then re-tested on the same years. Classic selection bias — **walk-forward validation is required before belief.** (t ≈ 0.9 on net per-trade mean — not yet statistically significant either.)
2. Capital utilization is tiny (1 lot, ~1.4% capital at risk per trade; equity vol 3.5%). CAGR 1.35% understates return-on-risk-deployed; scaling comes after validation, not before.
3. Exit mix: 90 hard-time / 33 target — most weeks ride to expiry midday; the profit target binds on a quarter of trades.

## Next

1. **Walk-forward:** fit gate threshold on 2021–2023, test 2024–2026 untouched (and reverse split).
2. Grid: z-max ∈ {0.3, 0.5, 0.7}, wing widths, target ∈ {50, 70, none}, twice-daily eval (H2).
3. Monthly vega variant through the same machinery.
