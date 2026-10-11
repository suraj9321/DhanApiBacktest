---
tags: [log]
---

# Decisions Log

Part of [[Home]]. One dated entry per decision; details live in the linked notes.

## 2026-07-16

- **Strategy core:** harvest the variance risk premium on Nifty weekly options; sell only when IV − forecast RV is statistically wide. → [[strategy-overview]], [[vrp-signals]]
- **Structure:** always-hedged iron condor (never naked); position sizing computed from bounded max loss, not margin or premium. → [[strategy-overview]]
- **Capital:** start ₹8L, scale to ₹20L on demonstrated performance.

## 2026-07-17

- **Trade window:** Friday entry → Tuesday expiry to capture weekend theta — *conditional on empirical validation* of post-markdown weekend theta capture; the backtest picks the final entry day. → [[trade-window]]
- **Adjustments:** formalized as a state-machine policy (delta-threshold rolls of the untested side, never adding size to defend). → [[adjustment-policy]]
- **Backtester architecture:** event-driven (minute-bar walking, per-leg cost model), decided because the adjustment policy requires intra-trade simulation. → [[adjustment-policy]], [[data-pipeline]]
- **Vault:** `notes/` is the Obsidian vault; strategy docs split into linked notes with [[Home]] as the index.

## 2026-07-17 (discovery answers)

- **Phasing:** backtesting first; automation (semi/full-auto), alerting, and AWS deployment designed only after backtest results. Development on Mac for now.
- **Risk limits (CONFIRMED):** four-layer defense per [[risk-framework]] — per-structure stop 1.5–2× credit (backtest param) → weekly hard stop 4% of trading capital → monthly circuit-breaker **5%** (user tightened from 8% proposal; implies mandatory downsizing after any weekly stop-out) → structural wing bound ≤ ~8% for gap scenarios. Cost model: explicit per-leg, 20%-of-gross as sanity band.
- **Capital:** ₹8L trading + ₹12L cash reserve for margin expansion only (never for size).
- **Scope widened:** backtest BOTH Nifty weekly and monthly expiries head-to-head. → [[trade-window]], H1 in [[ref-theta-gainers-iron-condor]]
- **Event weeks:** trade smaller (ride elevated vol), not skip — size multiplier is a backtest parameter. → [[risk-framework]]
- **Costs:** explicit per-leg cost model; user's 20%-of-gross figure kept as stress overlay/sanity check. → [[risk-framework]]
- **Dhan Data API subscription:** active — data pull can begin.
- **Workflow:** Claude builds, Suraj reviews; every proposal explained thoroughly with reasoning.
- **Tax:** deferred to final step.

## 2026-07-18

- **Monthly window:** NOT the last 4–5 days (redundant — the monthly in its final week IS the weekly contract; [[analysis-greeks-curves]]). Monthly = front-of-month **vega trade**: entry DTE ∈ {22, 15, 10} gated by vrp_month / iv_rank, exit by 5–10 DTE or target — never into the final week. Weekly stays v0.1 (gamma trade, vrp_z gated). H1 becomes gamma-harvest vs vega-harvest.
- **Backtester architecture approved for build:** event-driven design per [[architecture-backtester]] — anti-look-ahead wall (as-of signals, next-bar fills), defined-risk-only structure model, strategy-as-config (YAML grid), itemized per-fill costs, four-layer risk manager with veto power, golden-week + invariant tests.
