---
tags: [analysis, strategy]
date: 2026-07-17
---

# Analysis: T−1 Morning Entry → Expiry Midday Exit (the proposed window)

Part of [[Home]]. User's proposal (2026-07-17): enter Monday morning, exit at profit target or before the last ~30% of theta on expiry Tuesday. Era-agnostic implementation: **enter T−1 09:20, exit expiry 13:15 or at profit target**, minute-level paths, all 261 weekly cycles. Reproduce: `scripts/analyze_monday_entry.py`; table `meta.duckdb::analysis_monday_entry`.

## Results (unconditional, before costs, no wings)

**Short ATM straddle** (mean credit 181 pts ≈ 0.87% of spot):

| Exit rule | Mean | % of credit | Median | Win% | SD | Worst | Target hit |
|---|---|---|---|---|---|---|---|
| Hold to 13:15 | **+16.3** | 7.1% | +37.1 | 63.6% | 104.7 | −362.5 | — |
| 50% target | +15.7 | 6.8% | +51.4 | 65.1% | 101.1 | −362.5 | 41% |
| 70% target | +15.9 | 6.8% | +37.1 | 63.6% | 104.4 | −362.5 | 7% |

**t ≈ 2.5 (p ≈ 0.01)** — statistically significant positive mean, in sharp contrast to the weekend segment's zero ([[analysis-weekend-theta]]).

**Short 15Δ strangle** (mean credit only 39 pts ≈ 0.19% of spot):

| Exit rule | Mean | % of credit | Win% | SD | Worst | Target hit |
|---|---|---|---|---|---|---|
| Hold | +4.3 | 10.7% | 78.5% | 67.1 | **−437.6** | — |
| 50% target | +6.0 | 12.2% | 85.4% | 48.8 | −328.3 | 83% |
| 70% target | +4.3 | 8.2% | 80.1% | 60.1 | −328.3 | 72% |

Strangle t ≈ 1.0–2.0 — weaker; and the tail is obscene relative to credit (worst = **11× the credit received**). Worst weeks across both: Apr 2025, Feb 2022, Mar 2026, Jun 2024 elections, Feb 2026 — the usual suspects.

## Reading

1. **The segment itself carries a risk premium.** Unlike the weekend (fully priced), T−1 overnight + expiry morning pays sellers on average. Economically sensible: this is where gamma/pin risk is scariest, so premium sellers demand — and apparently receive — compensation. The VRP concentrates where the fear is.
2. **Profit targets act differently by structure:** on the straddle the 50% target rarely binds (41%) and changes little; on the strangle it binds 83% of weeks and clearly helps (win 85%, SD −27%). The user's "exit once weekly profit is hit" instinct adds real value for OTM structures.
3. **The 13:15 exit forgoes the terminal decay** (the 0.6%/session zone of [[analysis-theta-curve]]) **deliberately** — that zone is where the −300s happen intraday.

## Caveats before anyone gets excited

- **No costs yet.** Round-trip costs+slippage ≈ 3–5 pts. Straddle's +16 survives; strangle's +4–6 might not. Per-leg cost model comes with the backtester.
- **No wings yet.** Worst weeks (−362 straddle, −438 strangle) are exactly what wings cap. Wings cost premium → means shrink; tails shrink more. The real structure is the iron fly / condor version of this window.
- **Multiple-testing honesty:** this window was *selected* after looking at prior analyses; t≈2.5 on a selected hypothesis is promising, not proven. Needs walk-forward validation in the backtester and the [[vrp-signals]] filter on top (which should raise the mean and cut the tail by skipping poisoned weeks).
- Thu-era dominates the sample (219 vs 42 Tue-era cycles); era-consistency check pending.

## Status

**Working strategy shape (v0.1):** enter T−1 ~09:20 (condor/fly, wings per [[analysis-weekend-gaps]] asymmetry), profit-target ~50% of credit, hard exit expiry ~13:15, sized per [[risk-framework]], gated by the VRP filter once built. To be validated properly in the event-driven backtester with full costs.
