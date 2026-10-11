---
tags: [reference, strategy]
source: https://www.youtube.com/watch/Pgs77xukT7Q
---

# Reference: Theta Gainers — Monthly Iron Condor → Iron Fly

Part of [[Home]]. Raw transcript: [[ref-theta-gainers-transcript]]. Compare with our approach in [[strategy-overview]], [[vrp-signals]], [[adjustment-policy]].

Source: Face2Face interview (Vivek Bajaj / elearnmarkets) with Reyaansh Upadhyay ("Theta Gainers"). Ex-Infosys engineer, full-time options seller. **Practitioner's strategy — experience-driven, not math-driven.** Distilled here into testable rules, followed by a critical assessment.

## His strategy, distilled

**Instrument & timeframe:** Bank Nifty **monthly** expiry. He abandoned weekly in 2022: premiums too low, adjustment costs ate the edge, adjustments hard to place. *(Note: Bank Nifty weeklies no longer exist anyway post-SEBI 2024 cuts — monthly is the only choice there now.)*

**Entry:**
- Enter between the 1st–5th of the month (or the day after the previous monthly expiry), around 10:00–10:20am (after the opening-volatility window).
- Sell the **25Δ call and 25Δ put** ("high value" condor — premium rich enough to hit the monthly target in 5–8 days if the market cooperates, allowing early exit).
- Buy hedges at the **breakeven points** (≈ short strike ± total credit; lands around 17Δ). Wing width in his example: ~700 pts on Bank Nifty.
- **Gap stress-test at entry:** check the T+1 P&L for a ±700–800 pt overnight gap (~2–2.5%); if the loss is a trivial fraction of capital, the position is acceptable.

**Risk & sizing:**
- ₹5L notional capital, uses only ~half the margin (~₹2.5L) — the rest is buffer.
- **Stop: 4% of capital per month (₹20k).** Hit it → stop trading for the month. Only 12 trades a year; target win rate 10/12.
- Target: >4%/month gross; book early if reached in days rather than milking to expiry.
- Capital parked in Nifty BeES (bought on 5% index dips), pledged for ~91% margin — investment and trading margin double-use. Hedge buys require cash.

**Monitoring & adjustment (the core of it):**
- Check the position **only at ~9:45am and ~3:00–3:20pm**. Designed for people with jobs.
- **Trigger:** spot touches a short strike (evaluated at the 3pm check; also acts if within ~200 pts near close). No adjustment before the strike is tested.
- **The conversion:** book the untested side (in profit), then sell a new option on the tested side at *the same premium as the existing tested short* — lands near ATM (~44Δ) — converting the condor into an **iron fly**. Buy the matching hedge preserving the original wing width.
- **Iron-fly maintenance:** repeatedly roll hedges *closer* to spot when directionally cheap (pay 10–40 pts of debit to cut 100–200 pts of hedge gap), harvesting profit on hedges that have appreciated. Each roll shrinks the max-loss box, ratcheting worst case back under the ₹20k stop.
- Position bias after conversion: play for mean reversion ("market moves zig-zag; a one-way month needs war/pandemic-level news").

## Critical assessment (the mathematician's read)

**What's genuinely good — candidates to adopt/test:**

1. **The monthly-vs-weekly cost argument is real.** His empirical complaint — low weekly premium, adjustment costs eating the strategy — is exactly the cost-drag term we flagged in [[adjustment-policy]]. Our backtest should run a **monthly-expiry variant as a control** against the Friday→Tuesday weekly plan in [[trade-window]].
2. **Fixed-time monitoring (9:45am / 3:15pm) is a testable execution policy.** Checking twice a day vs. continuous monitoring is a discrete policy choice our event-driven backtester can compare directly. If twice-daily loses little, that's operationally huge.
3. **The ratcheting hedge-roll is legitimately risk-*reducing*.** Paying small debits to pull hedges closer after favorable moves shrinks the max-loss box monotonically. This is a disciplined, non-martingale adjustment — formalizable as: *when hedge-gap reduction cost per point < threshold, roll.* Worth adding to the [[adjustment-policy]] action set.
4. **The entry gap stress-test** (what does a ±2.5% overnight gap do to T+1 P&L?) is a clean pre-trade acceptance check. Cheap to compute; we should make it a formal entry constraint.
5. **Monthly loss circuit-breaker** (stop trading for the month once −4%) bounds behavioral tail risk, not just market tail risk. Sensible.

**Where the math is missing — treat with caution:**

1. **No volatility filter.** He sells every month unconditionally. There is no IV-vs-RV test, no IV-rank gate — precisely the Tier-1 signals in [[vrp-signals]]. His edge, if it exists, comes from adjustment discipline, not entry selection. Our VRP filter is orthogonal and should stack.
2. **The condor→fly conversion adds directional risk to recover a loss.** Selling a ~44Δ option into the trend, explicitly "playing for a bounce," is partially loss-recovery behavior — a soft form of the martingale we banned in [[adjustment-policy]]. In trending months (one-way moves without the bounce) this converts a small defined loss into a near-max loss. **Must be backtested against the simpler alternative: just close at the stop.**
3. **25Δ short strikes are aggressive.** Probability of touching ≈ 2×Δ ⇒ ~50% chance per side of the adjustment triggering. The strategy *plans* to adjust most months — so its P&L is dominated by adjustment dynamics, which is exactly the hardest thing to backtest honestly and the easiest to fool yourself about with one cherry-picked month on Opstra.
4. **Evidence quality is anecdotal:** one walked-through month (May, chosen because it was hard, to his credit), P&L screenshots from a 4-month-old account (₹5L realized on ₹17L, charges ~20% of gross — note how large that cost fraction is, confirming costs are first-order).
5. **"4%/month" framing** is the win-rate story, not the expectation. 10 wins × 4% − 2 losses × 4% ≈ 32%/year gross before slippage — consistent with our "anyone promising 5%/month is describing win rate" warning in [[strategy-overview]], and his own numbers show fat cost drag.

## Testable hypotheses extracted for our backtest grid

- **H1:** Monthly 25Δ condor + fly-conversion (his rules) vs. our static 10–15Δ weekly condor with stop — risk-adjusted comparison on identical data. *(His is Bank Nifty; we'd test on Nifty monthlies for comparability with our program.)*
- **H2:** Twice-daily (9:45/3:15) adjustment checks vs. continuous minute-level triggers — how much does monitoring frequency actually matter?
- **H3:** Hedge-ratcheting rolls on favorable moves: does adding this action to our policy improve the P&L distribution's left tail per rupee of debit spent?
- **H4:** Condor→fly conversion vs. plain stop-out when a short strike is tested — which has better tail behavior in trending months?
- **H5:** Does adding our Tier-1 VRP filter on top of his unconditional monthly entry improve his strategy's Sharpe? (If yes, filters and adjustments stack.)
