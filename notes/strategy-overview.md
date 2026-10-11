---
tags: [strategy]
---

# Strategy Overview

Part of [[Home]]. Signals live in [[vrp-signals]]; holding window in [[trade-window]].

## What the trade actually is, mathematically

Option selling is not "collecting rent." It is **harvesting the variance risk premium (VRP)**: the empirical fact that implied volatility systematically overprices subsequently realized volatility. For Nifty this premium exists and is well documented — India VIX has historically averaged a few points above realized vol.

For a delta-neutral short option position, the P&L decomposes as:

```
P&L ≈ ½ · Γ · S² · (σ²_implied − σ²_realized) · Δt    (summed over the holding period)
```

So the edge is positive **only when IV > subsequently realized vol**. That gives the entire research program:

1. Forecast realized vol for the coming week.
2. Compare against what the market is charging (IV).
3. Sell only when the spread is statistically wide.
4. Structure the position so the fat left tail is truncated.

Everything else — OI analysis, max pain, "market view" — is secondary noise until proven otherwise in the backtest.

> [!warning] The uncomfortable truth
> This trade has a **high win rate and negative skew**. You win small ~85% of weeks, and the distribution's left tail is where accounts die. The wings (the black-swan hedge) convert the unbounded tail into a known, bounded number. That bounded number is the only thing position sizing should be computed from — never the margin, never the premium.

## Structure: iron condor / iron fly, not naked strangles

The constraint "always hedged, minimal expenditure" points directly at the **iron condor**: sell an OTM call + OTM put, buy a further-OTM call + put as wings.

In India this has a second, huge benefit: hedged short options get **~60–70% SPAN margin reduction**.

| Structure | Approx. margin per lot | Max loss |
|---|---|---|
| Naked short strangle | ₹1.5–2L | Unbounded |
| Iron condor (with wings) | ₹40–70k | `(wing width − net credit) × lot size` — chosen in advance |

With ₹8L we can run 4–8 condors with a healthy buffer.

## India-specific facts to build around

*(some changed recently — verify current values when coding)*

- Nifty lot size is **75**; strike spacing 50 points near ATM.
- Weekly expiries now exist only for **Nifty (NSE, Tuesday)** and **Sensex (BSE, Thursday)** — SEBI killed the rest in late 2024 and reshuffled expiry days in 2025.
- **STT on option selling is 0.1% of premium**; add exchange charges, GST, stamp duty, and realistic slippage. For a strategy collecting small weekly credits, **costs are a first-order term, not a footnote** — the backtest must model them per leg.
- SEBI added **~2% extra ELM on expiry-day short positions**, and margin requirements expand when IV spikes — the capital buffer must survive mark-to-market margin expansion at exactly the moment the position is losing.

## Honest expectations

With ₹8L, disciplined sizing (risking 1–2% of capital per structure at max loss), and the VRP filter, a realistic target is **15–25% annualized on deployed capital**, with occasional losing months. Anyone promising "5% per month from premium selling" is describing the strategy's win rate, not its expectation.

The 5-year backtest window (mid-2021 → now) conveniently contains:

- June 2024 election-day ±6% whipsaw
- August 2024 yen-carry unwind
- April 2025 tariff crash

Excellent stress tests for the wing structure.
