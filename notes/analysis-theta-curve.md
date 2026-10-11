---
tags: [analysis, strategy]
date: 2026-07-17
---

# Analysis: Theta Decay Through the Expiry Cycle (Weekly vs Monthly)

Part of [[Home]]. Complements [[analysis-weekend-theta]] (which measured *realized capture*; this measures *where premium erodes*). Reproduce: `scripts/analyze_theta_curve.py`. Measure: ATM straddle as % of spot, 7 intraday marks/session, averaged over all cycles 2021–2026 (mean + IQR band).

![[theta-decay-curves.png]]

## Numbers

**Weekly** (entry ≈1.47% of spot at 4 sessions out → 0.08% at expiry close):

| Sessions-remaining step | Decay per session (% of spot) |
|---|---|
| 4→3 | 0.19 |
| 3→2 | 0.22 |
| 2→1 | 0.27 |
| **1→0** | **0.62** |

- **Last session holds 57% of the whole cycle's decay; last two sessions hold 75%.**
- ~45% of all decay happens *intraday on expiry day itself* (0.70% at expiry-morning 09:20 → 0.08% at close).
- The visible knee: the curve steepens from ~1.5 sessions out and goes near-vertical on expiry afternoon — the √τ law in the flesh.

**Monthly** (entry ≈3.12% of spot at 21 sessions out):

| Phase | Decay per session |
|---|---|
| 21→15 | 0.07 |
| 15→10 | 0.11 |
| 10→5 | 0.14 |
| 5→1 | 0.21 |
| **1→0** | **0.60** |

- Early monthly weeks drip at 0.07–0.14%/session — **3–8× slower than the weekly's late sessions** — while carrying full overnight/weekend gap risk the whole time.
- The monthly's final session converges to the same ~0.6% as the weekly's (they're the same contract by then).

## Interpretation — with the Analysis-2 warning attached

1. **Where the juice is:** weekly decay is overwhelmingly a last-48-hours phenomenon. A structure held T−4→T−2 earns ~0.2%/session; T−1→expiry earns 3× that.
2. **But decay ≠ capture.** [[analysis-weekend-theta]] proved the market pre-prices predictable decay (weekend capture ≈ 0 despite +74 pts predicted). The 0.62 final-session bar is paid *for bearing peak gamma* — expiry-day sellers earn it only net of pin risk and adjustment costs. This chart locates the premium erosion; it does **not** by itself say which segment is mispriced. That's the VRP filter's job.
3. **Monthly early phase is capital-inefficient theta:** slow drip, full tail exposure, margin locked. If monthlies earn their keep it must come from vega/selection effects, not raw theta — sharpens H1 of [[ref-theta-gainers-iron-condor]] for the backtest.
4. **Exit-rule shape confirmed:** the "don't milk the last 30%" rule from [[vrp-signals]] maps to exiting before the near-vertical zone unless deliberately running an expiry-day (gamma-priced) trade.
5. Wide IQR bands = regime dependence (calm 2023 vs 2022/2025 vol) — averages hide a factor-of-2 spread; the backtest must condition on IV level, not use these means as constants.
