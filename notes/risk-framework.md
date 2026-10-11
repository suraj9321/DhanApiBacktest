---
tags: [risk, decision]
---

# Risk Framework

Part of [[Home]]. Sizing philosophy in [[strategy-overview]]; intra-trade rules in [[adjustment-policy]].

## Capital structure

| Component | Amount | Role |
|---|---|---|
| Trading capital | ₹8L | Deployed in condors; all % limits computed on this |
| Cash reserve | ₹12L | Margin-expansion buffer ONLY — never for adding size |
| Total earmarked | ₹20L | Scaling gate decided after backtest |

> [!important] The reserve's job
> When IV spikes, SPAN margins expand exactly when positions are losing. The ₹12L exists so we are never force-liquidated at the worst prices. It is **not** extra firepower.

## Layered loss limits (defense in depth)

Each layer fires before the next; outer layers should rarely be touched.

1. **Per-structure stop** — exit a condor at 1.5–2× credit received (exact multiple = backtest parameter). Fires first, most weeks that go wrong.
2. **Portfolio weekly hard stop: 4% of trading capital (₹32k)** — everything flat for the week, no re-entry. *(User-set, 2026-07-17.)*
3. **Monthly circuit-breaker: 5% of trading capital → flat until next month.** Bounds behavioral tilt, not just market risk. *(User-set 2026-07-17, tightened from the 8% proposal.)*
   - **Interaction with layer 2:** one full weekly stop-out (−4%) leaves only 1% of monthly budget. Therefore, after any weekly stop-out, remaining weeks of the month must be **downsized so their worst case fits the remaining budget** (or sit out). Encoded in the backtester as a post-loss sizing rule, not just a kill line.
4. **Structural bound (the black-swan layer): wings sized so that ALL positions at max loss ≤ ~8% of trading capital.** This is the only layer that works through a gap — stops cannot execute through a weekend gap; wings can. Fri→Tue holding ([[trade-window]]) makes this layer non-negotiable.

> [!warning] Why a stop is not enough
> A stop-loss is an *instruction*, executed only when the market trades through it. A −5% Monday gap opens beyond every stop simultaneously. Only the bought wings bound that scenario — which is why structural max loss (layer 4) is sized independently of the stop (layer 2).

## The arithmetic to keep in mind

Expected gross capture ≈ 0.8–1.2% of capital per week (typical 10–15Δ condor credit at our sizing). One full 4% stop-out therefore erases ~4 winning weeks. The win rate needed to grow: with p(win) ≈ 85%, E[weekly] ≈ 0.85(+1%) + 0.15(−2.5% avg loss) ≈ +0.5%/wk gross before costs — thin. **This is why per-structure stops (layer 1) must catch most bad weeks before the portfolio stop does, and why costs are first-order.**

## Cost model (explicit, per leg — never a flat percentage)

Costs scale with *actions* (entries, exits, adjustments), not with profits, so an adjustment-heavy strategy must cost every leg:

| Component | Basis (verify current rates when coding) |
|---|---|
| Brokerage | ₹20/order (Dhan) |
| STT | 0.1% of premium, sell side |
| Exchange txn charge | ~0.035% of premium turnover |
| GST | 18% on (brokerage + txn charges) |
| Stamp duty | 0.003% buy side |
| SEBI fee | ₹10/crore (negligible) |
| **Slippage** | Half bid-ask spread per leg (model per strike moneyness; wings are wider than ATM) |

Ballpark: ₹500–850 per condor round trip vs. ~₹4–5k gross credit ⇒ **15–30% of gross** — consistent with the ~20% figure from [[ref-theta-gainers-iron-condor]]'s real P&L and the user's prior. The **20% flat drag is retained as a stress overlay/sanity check**, not as the model.

## Event weeks

Policy prior (user, 2026-07-17): **trade, ride the elevated volatility, but smaller.** Encoded as `event_size_multiplier ∈ [0,1]` (default 0.5) and optionally wider strikes; the backtest decides the value per event class (RBI, budget, Fed, elections). Rationale: event IV is rich — often when VRP is widest — but realized tails are fatter too; the trade-off is empirical.
