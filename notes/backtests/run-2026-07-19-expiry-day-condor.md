---
tags: [backtest, log]
date: 2026-07-19
---

# Backtest: expiry-day-only iron condor ("0DTE")

Part of [[Home]] · configs `expiry_day_v01.yaml` + grid variants · engine `src/backtest/strategy.py::pick_strikes_expected_move`.

Suraj's spec (2026-07-18): trade **only expiry day**, entering in the first 20–30 min, short strikes placed at the straddle-implied expected-move range, far wings capped so structural max loss ≤ 3× net credit, exit at 60% credit capture or 14:00 IST, whichever first.

## Mechanics implemented

- Shorts placed at `fwd ± em_mult × ATM straddle price` (the market's own expected-move estimate — no external vol model), snapped to nearest listed strike.
- Wings: farthest available strike D such that `D − net_credit ≤ max_loss_mult × net_credit`, scanned from the outside in (cheapest protective wing honouring the cap).
- Exit: 60% credit target, hard close 14:00, no delta-breach (the wing bound is the stop).

## Grid results (5y, ₹8L capital)

| em_mult | max_loss cap | intraday stop | Trades | Win% | Return/5y | Sharpe |
|---|---|---|---|---|---|---|
| 1.0× | 3× credit | none (spec as given) | 197 | 65% | **−16.9%** | −0.61 |
| 1.0× | 3× credit | 1.5× credit | 197 | 65% | −11.7% | −0.46 |
| 1.25× | 3× credit | none | 50 | 58% | −11.4% | −0.73 |
| 1.25× | 3× credit | 1.5× credit | 50 | 58% | −7.9% | −0.60 |
| 1.5× | 3× credit | either | 0 | — | 0% | — (solver found no feasible wing under a 3× cap this far out) |
| 1.25× | 5× credit | none | 229 | 70% | −17.6% | −0.75 |
| 1.25× | 5× credit | 1.5× credit | 229 | 68% | −8.6% | −0.47 |
| 1.5× | 5× credit | none | 99 | 72% | −8.2% | −0.51 |
| 1.5× | 5× credit | 1.5× credit | 99 | 70% | **−5.0%** | −0.42 |

**Every configuration tested stayed net negative.** The pattern is monotonic and mechanically clear:

1. **The 3×-credit max-loss cap is tight at 1.0–1.25× expected-move shorts** — wings land close enough that a full structural loss realizes before 14:00 on a meaningful fraction of trades. Win rate stays 58–65% but avg loss (₹5–8k) dwarfs avg win (₹3–4k).
2. **Widening the shorts and loosening the cap both push win rate up** (to 72%) but do nothing for the loss asymmetry alone — the stop is what actually improves returns everywhere it's added (+4 to +9 points across every combination).
3. Nothing crossed into positive territory. Underwriting the single highest-gamma day of the cycle with only ~4.5 trading hours of decay appears structurally harder than the weekly z-band fly ([[run-2026-07-18-fly-series]]): realized intraday moves have been outrunning what a 1.0–1.5× straddle-implied range prices in.

## vrp_z relationship (in-sample, unconfirmed)

Bucket attribution of the base run's 197 trades against entry-day `vrp_z` showed the **opposite** sign from the weekly fly: this trade profits on stress weeks (z > 0.5) and bleeds in the calm mid-band. Plausible mechanism: high IV → wider expected-move shorts → fatter overpricing cushion. Not validated; same in-sample caveat as everything else on this project until walk-forward is run.

## Next

Not pursued further this session — deprioritized in favor of the range-breakout strangle ([[run-2026-07-20-range-strangle]]) per Suraj's redirect. If revisited: wider em_mult (2×) with the loose cap + stop is the next untested cell; a vrp_z gate (as with the fly) is also untested here.
