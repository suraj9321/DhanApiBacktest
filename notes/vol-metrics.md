---
tags: [infra, signals]
date: 2026-07-17
---

# Vol-Metrics Library (roadmap step 3)

Part of [[Home]]. Code: `src/pipeline/vol_metrics.py`; build: `scripts/build_vol_metrics.py`. Output: `data/parquet/signals/daily_signals.parquet` + `meta.duckdb::daily_signals` — one row per trading day, 2006→now (IV-era columns from Aug 2021). Feeds the [[vrp-signals]] entry gate; consumed by the backtester.

## Components

**RV forecasters** (all annualized %, no look-ahead by construction):
- `rv_cc21` — 21d close-to-close rolling. `rv_ewma` — EWMA(0.94).
- `rv_garch` — GARCH(1,1), parameters refit each January on prior data only, filtered forward.
- `rv_har5` — HAR-RV in **log-variance space** with half-variance bias correction; inputs = daily RV from 5-min returns **+ overnight gap²**; quarterly expanding refits. Forecast horizon: next 5 sessions.

**IV series:** single **parity-consistent ATM IV** inverted from the straddle price (Black-76 on implied forward) — immune to the vendor CE/PE IV asymmetry from [[validation-report]]. Sampled 15:15 (signal) and 09:20 (entry morning); dying-contract IVs (τ < ~half day) excluded. `cm7_iv`/`cm30_iv`: constant-maturity interpolation in total variance (kills the expiry sawtooth; expiry-day fallback = monthly).

**Signal columns:** `vrp_week = cm7_iv − rv_blend` (horizon-matched), `vrp_month = cm30_iv − rv_blend`, `vrp_z` (252d z-score), `iv_rank_1y`, `term_slope = cm30 − cm7`, `vix`. `rv_blend` = HAR where available, else EWMA. Columns marked `_EVAL` are look-ahead and forbidden in signal generation.

## Diagnostics (2021+ out-of-sample, vs realized next-5-session vol)

| Forecaster | corr | MAE | bias |
|---|---|---|---|
| rv_har5 | 0.45 | **2.66** | −0.37 |
| rv_ewma | 0.51 | 3.78 | −0.47 |
| rv_garch | 0.50 | 4.13 | +0.66 |
| cm7_iv | **0.66** | 3.59 | +0.53 |
| vix | 0.69 | 4.10 | +1.58 |

Honest reading: **IV-based measures out-rank pure RV models at predicting future vol** — the market's forecast is good; the VRP is a *premium level*, not a market error. The filter's job is to find days when that premium is unusually wide, not to "outsmart" IV.

## The VRP, measured

| Year | Mean vrp_week | % days > 0 |
|---|---|---|
| 2021 | +1.96 | 82% |
| 2022 | +1.06 | 66% |
| 2023 | +0.98 | 79% |
| 2024 | +2.16 | 89% |
| 2025 | +1.91 | 85% |
| 2026 | +1.95 | 76% |

Mean +1.61 vol pts across the sample — the premium exists in every year, thinnest in 2022–23, fattest in 2024. corr(vrp, term_slope) = −0.44: the premium widens as the term structure flattens/inverts (stress pricing).

## Build-quality notes (defects caught by diagnostics before shipping)

1. Expiry-day 15:15 "weekly IVs" (τ≈15 min) poisoned ~20% of rows → excluded via τ floor; cm7 falls back to monthly.
2. Raw-variance HAR had +2.3 bias (crash-week outliers dominate OLS) → log-space + ½σ² correction fixed it (bias −0.37).
3. VRP originally defined vs raw weekly ATM IV (maturity sawtooth) → redefined vs constant-maturity cm7, horizon-matched to the 5-session forecast.

Coverage: 94% of days since Aug 2021 have `vrp_week`; backtester forward-fills ≤ 1 day.
