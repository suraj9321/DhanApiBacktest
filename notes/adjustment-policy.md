---
tags: [strategy, risk]
---

# Adjustment & Resizing Policy

Part of [[Home]]. Exit rules that end a trade are in [[vrp-signals]]; this note covers *managing* a live trade.

**Principle: a state-machine policy, not discretion.**

## Position state = three numbers

1. Net delta of the structure.
2. Standardized distance of spot to each short strike: `d = ln(K/S) / (σ√τ)` (units of remaining expected move).
3. Open P&L as a fraction of credit received.

Adjustment rules are thresholds on this state, e.g.:

> When a short strike's delta exceeds ~25–30 → roll the *untested* side toward spot (recenters delta, collects more credit). If breached again → cut size or exit. **Never add size to defend.**

## Two hard warnings

> [!danger] No disguised martingales
> Most retail adjustment schemes add risk on adverse moves to recover losses — converting a bounded-loss structure back into an unbounded one through a different door. Resizing may only *reduce* risk on adverse moves; adding size is reserved for fresh entries at favorable conditions (e.g., IV spike with the VRP filter green).

> [!warning] Every adjustment costs two more legs
> Each roll pays STT + slippage + spread-crossing twice over. Trigger thresholds are backtest parameters to optimize, not virtues. A rule that adjusts half as often at nearly the same risk usually wins after costs.

## Architecture implication

The backtester must be genuinely **event-driven** — walking minute bars intra-trade, applying the adjustment policy, costing each roll — not a vectorized entry/exit-only simulator. No new data required beyond [[data-pipeline]].
