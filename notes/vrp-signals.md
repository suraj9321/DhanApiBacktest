---
tags: [strategy, signals]
---

# VRP Signals — Entry & Exit

Part of [[Home]]. Thesis in [[strategy-overview]]; data needed to compute these in [[data-pipeline]].

What "high confidence entry" means quantitatively — ranked by how much the math can be trusted.

## Tier 1 — the VRP core (this *is* the strategy)

1. **IV vs. forecast RV spread.** Compute realized vol forecasts from spot minute/daily data — EWMA, GARCH(1,1), and HAR-RV. Entry condition: `ATM IV − RV_forecast` above a threshold, ideally as a z-score against its own history.
   > [!warning] EMPIRICALLY CORRECTED (2026-07-18, [[run-2026-07-18-fly-series]])
   > For the weekly gamma trade the naive rule **inverts in the right tail**: weeks with unusually wide VRP (z ≥ 0.5) are stress signatures — IV outruns lagging RV forecasts exactly when realized vol is about to overshoot; they lose (win 37–42%). The working gate is a **band**: `vrp_week > 0 AND vrp_z ≤ 0.5`. High iv_rank quartile similarly adverse. Pending walk-forward confirmation.
2. **IV rank / percentile** over a 1-year lookback — sell rich vol, stand aside when vol is cheap.
3. **Expected move vs. historical distribution.** ATM straddle price ≈ `0.8 × S · σ · √T` gives the market-implied weekly move. Compare against the empirical distribution of Nifty weekly moves: what fraction of historical weeks stayed inside the range the market is currently paying you to underwrite? A direct, distribution-free probability estimate.

## Tier 2 — regime and strike placement

4. **Strike selection by delta** (e.g., short strikes at 10–15Δ; probability of *touching* a strike ≈ 2× its delta — useful for stop planning) or by multiples of expected move.
5. **India VIX level and term structure** (weekly vs monthly IV) — backwardation = stress; don't sell into it blindly.
6. **Event calendar filter:** RBI policy, Union Budget, elections, Fed/FOMC, CPI prints. These are *known* variance injections; the clean move is to skip or widen — the backtest will tell us which.

## Tier 3 — popular but unproven (we test, we don't assume)

- OI walls as support/resistance, PCR, max pain. Retail India loves these; they must survive a 5-year out-of-sample test before earning a place in the entry logic.

## Exit logic (where most risk-adjusted return actually comes from)

- **Profit take** at ~50–70% of max credit captured — the last 30% of theta is earned while gamma is at its maximum; the math says don't stay for it.
- **Stop** on credit multiple (loss = 1.5–2× credit received) **or** short-strike delta breaching ~30, whichever fires first.
- **Time rules:** whether to hold through expiry morning or always exit T−1 evening is an empirical question the minute-level data can answer precisely.

Intra-trade management rules live in [[adjustment-policy]].
