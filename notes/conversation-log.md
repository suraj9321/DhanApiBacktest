---
tags: [log]
---

# Conversation Log

Part of [[Home]]. Verbatim record of strategy discussions; distilled outcomes go to [[decisions-log]].

## 2026-07-17 — Trade window & adjustments

**Suraj:** I am planning to start the trade on Friday to Tuesday, as the theta decay is good throughout the weekend. Also plan to adjust and resize the position once we see some good movement factored into our model.

**Claude:** Good — that pins down the trade window. Three points of pushback/refinement:

1. **Weekend theta is partially an illusion.** The Black-Scholes clock runs on calendar time, so naively Friday→Tuesday captures ~4 of the option's last 7 days of decay for only 2 trading sessions of risk. But market makers mark IVs down into Friday close (pre-crushing the weekend) and mark them back up Monday morning — part of the weekend decay is already removed from the price by the time you sell on Friday. The honest question is empirical: after the Friday IV markdown, does selling Friday ~3pm and holding to Tuesday still deliver positive expectancy net of costs? Our minute-level data answers this directly: compute the realized theta-capture of a Friday-close 15Δ condor, segment by segment (Fri close→Mon open, Mon session, Tue session) across ~250 weeks. If the weekend segment's capture is near zero, we enter Monday morning instead and skip the gap risk entirely. Let the data pick.

2. **The weekend is exactly when you can't adjust.** Friday→Tuesday means the position lives through two days of global news (US Friday session, futures reopen Sunday night IST) while you're locked out. Weekend gaps are precisely the black-swan channel — this is where the wings earn their keep, and it argues for placing wings closer (accepting lower net credit) on this schedule than a Monday-entry schedule would need. The Nifty Friday-close→Monday-open gap distribution over 5 years is one of the first things to tabulate.

3. **Formalize adjustments as a state-machine policy, not discretion.** Position state = net delta of the structure, standardized distance of spot to each short strike (`d = ln(K/S)/(σ√τ)`), and open P&L as a fraction of credit. Adjustment rules are thresholds on this state — e.g., when a short strike's delta exceeds ~25–30, roll the untested side toward spot; if breached again, cut size or exit; never add size to defend. Two warnings: (a) most retail adjustment schemes are disguised martingales — adding risk on adverse moves converts a bounded-loss structure back into an unbounded one; resizing may only reduce risk on adverse moves, and adding size is reserved for fresh entries at favorable conditions. (b) Every adjustment is two more legs of STT + slippage + spread-crossing — trigger thresholds are backtest parameters to optimize, not virtues.

**Architecture implication:** the backtester must be genuinely event-driven (walking minute bars intra-trade, applying the policy, costing each roll), not a vectorized entry/exit-only simulator. No new data requirements.
