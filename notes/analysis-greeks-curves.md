---
tags: [analysis, strategy]
date: 2026-07-17
---

# Analysis: Greeks Through the Expiry Cycle

Part of [[Home]]. Companion to [[analysis-theta-curve]]. Reproduce: `scripts/analyze_greeks_curve.py`. ATM-straddle means across all cycles 2021–2026, weekly vs monthly on a shared sessions-remaining axis.

![[greeks-curves.png]]

## Numbers

| Greek (ATM straddle) | Weekly: cycle start → expiry | Monthly: cycle start → expiry |
|---|---|---|
| Gamma (Δdelta per 1% spot move) | 0.48 → 3.79 (**×8**) | 0.23 → 3.52 (**×15.6**) |
| Vega (% of spot per vol-pt) | 0.104 → 0.009 | **0.228** → 0.009 |
| Theta (model, %/day) | 0.117 → 1.894 | 0.050 → 2.159 |

## Findings

1. **Theta and gamma are the same curve.** The panels are mirror twins — empirical confirmation of the identity θ ≈ −½Γσ²S²: *you are paid theta exactly in proportion to the gamma you carry.* There is no theta without gamma; every "juicy decay zone" is equally a "delta-explosion zone." The +16 pts/wk of [[analysis-monday-entry]] is compensation for bearing the ×8 gamma ramp — not free money left on a table.
2. **Weekly and monthly curves overlay perfectly at equal sessions-remaining** — near expiry the monthly *is* the weekly (same contract). Expiry-proximity, not contract label, determines the risk profile.
3. **Monthly is the vega trade.** At cycle start, monthly ATM vega (0.228%/vol-pt) is 2.2× weekly's. A 1-pt IV re-mark moves a monthly position ~0.23% of spot. Consequence for the vol factor: **IV-rank/VRP level matters most for monthly entries; short-horizon RV forecasting matters most for weekly.** Sharpens H1 ([[ref-theta-gainers-iron-condor]]): monthly condors are primarily selling vol level, weekly condors primarily selling gamma.
4. **Delta polarization (strike hardening):** at 4 sessions out, ATM+1…+4 deltas sit packed (0.46/0.40/0.34/0.29); by expiry they spread to 0.17…0.02. The same rupee distance means little early and everything late. So **delta-based strike selection auto-adapts** (fixed-delta strikes move closer in rupees as τ falls) while rupee-based selection silently changes risk through the week — validates the [[vrp-signals]] choice of delta-quoted strikes and the delta-threshold triggers in [[adjustment-policy]].

## Structure decision (user, 2026-07-17)

**All strategy work proceeds with hedged structures only — iron condor / iron fly.** Straddle/strangle runs above were measurement instruments for window economics, never tradeable candidates. Wings: put wing closer than call wing per [[analysis-weekend-gaps]] asymmetry. Next: vol-metrics library (RV forecasts, IV rank, VRP series) so entries are volatility-gated per [[vrp-signals]].
