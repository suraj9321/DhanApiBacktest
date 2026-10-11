---
tags: [analysis, strategy]
date: 2026-07-17
---

# Analysis 2: Weekend Theta Capture — Verdict on the Friday Window

Part of [[Home]]. Answers the central question of [[trade-window]]; gap context in [[analysis-weekend-gaps]]. Reproduce: `scripts/analyze_weekend_theta.py`; detail table `meta.duckdb::analysis_weekend_theta` (225 Fri→Mon weekends, 2021–2026).

## Method

Short the ATM straddle each Friday 15:15, track the **same strike** to Monday 09:20. Compare realized P&L against the pure-theta prediction (Black-76 revalue, only τ reduced by 2.6 days, IV and forward frozen). Weeks where the gap left our strike window (3 of 225 — including Apr 2025 −4.5%) use an intrinsic-floor exit and are reported, not hidden.

## Results

| Sample | n | Entry straddle | Pure-theta pred | Realized mean | Median | Win% | **Capture ratio** |
|---|---|---|---|---|---|---|---|
| All clean weeks | 222 | 260.5 | +73.7 | **−0.7** | +8.8 | 66.7% | **−0.01** |
| Thu-expiry era | 186 | 267.9 | +69.6 | −1.8 | +8.0 | 66.7% | −0.03 |
| Tue-expiry era | 36 | 221.8 | +95.2 | +5.0 | +11.2 | 66.7% | 0.05 (t≈0.6, n.s.) |

**The mechanism, visible in the data:** IV marks down into Friday and re-marks up Monday morning by **+4.0 vol points on average** (12.75 → 16.72). Theta earned over the weekend ≈ gap losses + Monday vega re-markup. The market prices the weekend almost exactly.

**The shape:** 67% of weekends win small (median +9 pts); the tail destroys the mean — worst: **−784** (Apr 2025 tariff), −214 (Feb 2022 pre-invasion), −210 (Mar 2026), −191, −189… Classic negative skew: dimes in front of the steamroller, and net of the steamroller, the dimes sum to zero.

## What this does and does not say

1. **Does say:** *unconditional* Friday-entry weekend holding of ATM premium has **zero expected edge** — the "theta decays all weekend" narrative is an illusion of calendar accounting; the market already removed it from Friday prices. My earlier caveat in [[trade-window]] is confirmed quantitatively.
2. **Does say:** Monday-morning entry gets a **higher IV** (+4 pts) for Mon→Tue exposure with **no weekend gap risk** — on segment evidence, Monday entry likely dominates Friday entry risk-adjusted. Proper head-to-head belongs to the backtester.
3. **Does NOT say premium selling is dead.** This measured selling *every* week, ATM, unmanaged. Our thesis was never unconditional: the entire [[vrp-signals]] design sells only when IV − RV forecast is statistically wide. A zero unconditional mean with 67% win rate means the edge, if any, lives in **selection** (which weekends are overpriced), **structure** (15Δ condor ≠ ATM straddle exposures), and **management** — exactly what the backtester tests. This result makes the VRP filter load-bearing, not optional.
4. Tue-expiry era subsample (the user's actual regime) is small (n=36) and statistically indistinguishable from zero.

## Consequences

- **[[trade-window]] verdict: Friday entry is not supported by unconditional evidence.** Working hypothesis flips to **Monday-morning entry** (post-remarkup IV, no weekend gap), with Friday-entry-under-VRP-filter kept as a backtest variant, not the default.
- Weekend holds, when the filter does trigger one, must be sized against [[analysis-weekend-gaps]] tails (−784 pts realized once in our own 5-year sample).
