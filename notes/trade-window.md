---
tags: [strategy, decision]
---

# Trade Window: Friday Entry → Tuesday Expiry

Part of [[Home]]. Decision recorded in [[decisions-log]]; full exchange in [[conversation-log]].

**Rationale (Suraj):** capture theta decay through the weekend.

> [!warning] Weekend theta is partially an illusion
> The Black-Scholes clock runs on calendar time, so naively Friday→Tuesday captures ~4 of the option's last 7 days of decay for only 2 trading sessions of risk. But market makers mark IVs *down* into Friday close (pre-crushing the weekend) and mark them back up Monday morning — part of the weekend decay is already removed from the price by Friday afternoon.

**The empirical question:** after the Friday IV markdown, does selling Friday ~3pm → Tuesday still deliver positive expectancy net of costs?

**Testable with our minute data:** compute realized theta-capture of a Friday-close 15Δ condor, segment by segment (Fri close→Mon open, Mon session, Tue session) across ~250 historical weeks. If the weekend segment's capture is ≈ 0, enter Monday morning instead and skip the gap risk. **Let the data pick the entry day.**

## Weekend = the unadjustable window

Friday→Tuesday holds through two days of global news (US Friday session, futures reopen Sunday night IST) with no ability to adjust. Weekend gaps are exactly the black-swan channel → argues for **closer wings (lower net credit)** on this schedule than a Monday-entry schedule would need.

**First analysis task:** tabulate the Nifty Friday-close→Monday-open gap distribution over 5 years (data via [[data-pipeline]]).

---

## VERDICT (2026-07-17): the data spoke — see [[analysis-weekend-theta]]

Across 222 clean weekends: realized weekend capture of a Friday-15:15 short ATM straddle = **−0.7 pts mean vs +73.7 pts pure-theta prediction (capture ratio ≈ 0)**. Monday's IV re-markup (+4.0 vol pts) plus gap losses consume the calendar decay entirely. The weekend-theta caveat above is confirmed: **the market prices the weekend almost exactly.**

**Working hypothesis is now Monday-morning entry** (higher entry IV, no weekend gap exposure). Friday entry survives only as a conditional variant (VRP filter green) in the backtest grid. Gap tails for any weekend hold: [[analysis-weekend-gaps]].
