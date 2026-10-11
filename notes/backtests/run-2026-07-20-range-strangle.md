---
tags: [backtest, log]
date: 2026-07-20
---

# Backtest: range-breakout strangle (naked, stop-loss only)

Part of [[Home]] · config `range_strangle_v01.yaml` · engine `src/backtest/range_engine.py` (new, independent-leg shape — not the condor/fly Structure model).

Source: two slides from a public strike-selection/position-sizing deck (twitter.com/mitesh_engr, 2021-07-04) that Suraj asked to test directly. **Explicit deviation from the hedged-only mandate** ([[risk-framework]]): Suraj chose to test this naked (stop-loss risk control only) as a pilot; cheap far-OTM wings to be added later only if the idea shows edge.

## Mechanics (interpretation choices flagged — the slides leave several things unstated)

- **Range** = prior ISO calendar week's daily high/low (Nifty spot). Entry Monday 09:20 — the T−1 window already validated in [[analysis-monday-entry]].
- **Position classification**: `loc = (spot − low) / (high − low)`. loc ≤ 0.30 → sell calls only; loc ≥ 0.70 → sell puts only; else → sell both (strangle). *"Near" was undefined on the slide — tercile split is my choice.*
- **Strikes**: short call ≈ high×1.015, short put ≈ low×0.985 (1.5%, midpoint of the slide's 1–2%), snapped to nearest listed strike.
- **Breach stop + flip**: if spot crosses the boundary against an open leg, exit next-bar and immediately sell the opposite side at spot×(1∓1.5%) — one flip per week only, no further breach-stop on the flipped leg (direction "confirmed" per the slide's language).
- **Premium stop** (from the position-sizing slide): exit a leg if its price reaches 2.5× the entry (sell) credit.
- **Weekly ROI target** (also from the sizing slide, replacing an earlier 60%-of-credit per-leg target): close all open legs for the week once realized+open P&L reaches +0.75% of total capital (slide's stated range: 0.5–1%).
- **Hard close**: Tuesday 13:15 (same validated weekly hard-time as elsewhere).
- **Sizing**: no structural hedge exists, so nothing bounds loss the way a wing does. Sized against `(premium_stop_multiple − 1) × entry credit` — the same pattern the condor engine uses (the configured stop both caps and sizes the trade) — **and** capped by a rough margin proxy (12% of notional, a SPAN+exposure stand-in; **must be calibrated against Dhan's live margin API before real money**, same treatment as the slippage model in `costs.py`).

## Two bugs caught before trusting the numbers

1. **Sizing collapse**: an early version proxied risk as `gap_multiple × |strike − boundary|`. When the nearest *available* strike (data only covers ATM±10 offsets) landed almost exactly on the boundary, that denominator collapsed toward zero and produced a 2,666-lot position on one entry (−₹89,978 in a 3-month smoke test). Fixed with a minimum-distance guard (skip the entry if no listed strike clears at least half the intended cushion) and by sizing against the premium stop instead of a distance proxy.
2. **Naive premium-based sizing alone** would let cheap far-OTM premium buy unrealistically large notional (a broker's real constraint is margin, not premium). Added the margin-percentage cap described above; without it the first flip trade would have sized to 53 lots (~₹7.3 crore notional) on a single leg.

## Results, 5 years (₹8L capital, 2021-01 → 2026-07)

| Metric | Value |
|---|---|
| Total return | **+1.82%** |
| CAGR | 0.37% |
| Sharpe | 0.21 |
| Max drawdown | −3.49% |
| Trades (leg-episodes) | 102 |
| Win rate | 89.2% |
| Avg win / avg loss | +₹871 / −₹5,423 |
| Profit factor | 1.33 |
| Worst trade | −₹17,788 |
| Costs as % of gross wins | 10.3% |
| Exit mix | hard_time 88, breach_stop 7, premium_stop 6, target_roi 1 |

**Classic high-win-rate / negative-skew naked-selling profile.** 88 of 102 trades (86%) simply ride theta to Tuesday's hard close and win small (+₹791 avg). The 13 stop-driven exits average large losses (breach_stop −₹2,754, premium_stop −₹6,544) but are rare enough that the frequency edge still wins net — barely: +1.82% over 5 years is close to flat, and year-by-year it visibly isn't smooth (+₹8,921 / +₹15,131 / **−₹12,534** / **−₹9,987** / +₹13,874 / +₹4,233 partial). Two of five years were net losers.

### Finding: puts carried the entire edge

| Side | Trades | Total P&L | Mean |
|---|---|---|---|
| PE (put) | 36 | **+₹19,890** | +₹552 |
| CE (call) | 66 | **−₹251** | −₹4 |

Selling calls near range-highs was flat over 5 years; selling puts near range-lows did all the work. Consistent with Nifty's known upward index drift over this period — a rising market makes "sell puts on weakness" a friendlier bet than "sell calls on strength," independent of anything the range-heuristic itself is doing. This is a **directional tailwind riding on the strategy's back**, not necessarily evidence the range logic has edge — worth testing on a flatter or down-trending sub-period before believing it.

### Finding: the flip mechanism is rare and its two worst outcomes are its costliest trades

Only 7 flips fired in 5 years. Two of them (2023-02-01 CE, 2024-11-06 PE) were the run's largest single losses (−₹17,788 and −₹6,519) — the flip chased a move that had already happened and then got stopped out again on continuation or reversal. The other 5 flips were harmless (small hard_time wins). Sample is far too small (n=7) to judge the flip rule on its own merits; it currently reads as a tax on the strategy rather than a benefit, but that's not statistically established either way.

### Data-quality note

Quote fallbacks were much heavier here than in the condor/fly backtests (7,616 ffill + 2,902 intrinsic, vs. low hundreds previously) — the range-implied strikes sit farther from ATM than our condor configs typically reach, closer to the edge of the ATM±10 pull window, where minute-level liquidity/quote coverage thins out. Exit fills near that edge lean more on forward-fill/intrinsic fallback pricing than elsewhere in this project; treat P&L precision on the widest-range weeks with slightly more skepticism than the fly-series numbers.

## Mandatory caveats

1. **Naked, no hedge** — explicit, temporary decision (Suraj, 2026-07-20). The worst realized trade (−₹17,788) came from a next-bar-fill gap through the premium stop on a fast-moving day — precisely the tail-risk scenario the hedged-only mandate exists to cap. A real gap event (weekend or intraday) is not bounded here the way it is in the condor/fly work.
2. **Margin proxy is a placeholder** (12% of notional) — not calibrated against Dhan's actual SPAN+exposure margin. Position sizes, and therefore all P&L figures, would shift under a correctly calibrated margin model.
3. **In-sample everything** — thresholds (loc terciles, 1.5% distance, 0.75% weekly ROI target, 2.5× premium stop) are all taken directly from the source slides or set by me at their stated midpoints, not fit to this data — so this run is closer to an honest out-of-sample test of the *slide's own numbers* than prior in-sample-fit work here. That's a genuine point in its favor. It has not, however, been walk-forward tested across sub-periods, and n=102 trades (13 of them the stop-driven tail events that matter most) is a thin sample for a strategy whose return profile is dominated by rare large losses.
4. Utilization is low (2–5 lots), consistent with everything else in this project so far — return-on-capital-deployed is understated by the headline CAGR.

## Follow-up: hedged variant (2026-07-20)

Per Suraj's decision to add the wing ("lets add some hedge"): `range_strangle_hedged_v01.yaml`, `hedge.width_pts: 300`, otherwise identical mechanics. Once a real wing exists, max loss becomes **exact** (`wing_width − net_credit`) rather than the naked run's premium-multiple proxy — same pattern as the condor/fly engine, so the rough 12%-of-notional margin guess was dropped for this path entirely.

### Blocking data constraint found before the first run meant anything

At `width_pts=300`, **only 2 of 319 leg-attempts** had a listed strike far enough out to hedge with — not "a worse wing than intended," but *no wing at all* was representable in the data 91.6% of the time. Root cause: our options pull only covers ATM±10 strikes *relative to each day's own spot* (`src/pipeline/config.py`). The short strike here is anchored to **last week's** range boundary, not today's spot — after a week of drift it often already sits near the edge of that ±10 window, leaving nothing beyond it for a wing.

Presented this as a real fork to Suraj (pull wider strike data vs. accept whatever room exists vs. only trade the rare weeks with full room) — **chose to test with whatever's available first**, no new data pull. The existing strike-snapping logic already does this correctly (nearest-to-target degrades gracefully to "farthest listed strike" when the target is unreachable, only skipping when literally zero strikes exist beyond the short) — no code change was needed to honor that choice.

### Result: the compromise doesn't work either

| Metric | Naked | Hedged (whatever fits) |
|---|---|---|
| Total return | +1.82% | **−0.84%** |
| Sharpe | 0.21 | −0.99 |
| Max drawdown | −3.49% | **−0.90%** |
| Trades | 102 | **29** |
| Win rate | 89.2% | 48.3% |
| Profit factor | 1.33 | 0.31 |
| Worst trade | −₹17,788 | **−₹2,063** |
| Costs / gross wins | 10.3% | **239.5%** |

The tail risk is genuinely capped — worst trade drops from −₹17,788 to −₹2,063, and max drawdown from −3.49% to −0.90%, exactly what a hedge is supposed to do. But the trade count dried up to 29 over 5 years, achievable wing widths were mostly 50–100 points (median 100, vs. the intended 300), and those thin spreads (credit as low as ₹1.10–2.05) get **completely dominated by fixed per-order costs** (₹20 brokerage × 4 legs, plus statutory charges) — costs eat 2.4× the gross wins.

**Worse: hedge availability didn't just stay thin, it collapsed to zero.** Year-by-year room beyond the short strike:

| Year | Hedgeable weeks | Mean room (pts) |
|---|---|---|
| 2021 | 17% | 12.1 |
| 2022 | 8% | 6.8 |
| 2023 | 25% | 18.5 |
| 2024 | 2% | 0.8 |
| 2025 | **0%** | 0 |
| 2026 | **0%** | 0 |

Every single hedged trade in the run happened before 2024-03; **the strategy has been mechanically untradeable under this data for the last ~2.5 years.** Likely cause: Nifty's price level rose from ~18,000 (2021) to ~25,000+ (2025-26) over the window. The short strike's distance from the boundary scales with spot (1.5% of a bigger number = more points), while the ATM±10 pull window is fixed in strike *count* — if strike spacing didn't widen proportionally, that fixed-count window shrinks in *relative* terms as the index appreciates, eventually swallowing the entire window before any wing room is left.

### Conclusion

"Use whatever hedge fits" is not a viable path with the current dataset — it isn't a matter of accepting a slightly-worse wing, the wing became **unavailable entirely** for the back half of the test period. A genuine hedged backtest of this idea requires re-pulling wider strike data (e.g. ATM±20, or better, a fixed points-based offset instead of a strike-count offset so coverage doesn't shrink as the index rises) before this can be evaluated properly. Flagging this back to Suraj as the concrete next decision.

## Revised exit rules (2026-07-23)

Suraj supplied a cleaner, classical exit framework, treated as **replacing** the weekly-capital-ROI target (not additive): breach-of-S/R unchanged; profit target now **per-leg premium decay of 80%** (was weekly ROI 0.75%); stop-loss unchanged at 2.5× premium; sizing tightened to **1.5% per trade** (midpoint of stated "1–2%"), down from 2.5%. `configs/range_strangle_v01.yaml` updated; `profit_decay_target_pct` added to `range_engine.py`.

Re-run, 5y naked: **+1.32%** (was +1.82%), Sharpe 0.17 (was 0.21), maxDD −3.39% (was −3.49%), still 102 trades, win 89.2%, PF 1.28. Exit mix shifted heavily toward the new target (63 trades, up from ~1) and away from riding to hard_time (26, down from 88) — the 80%-decay rule takes profits much earlier in the week than "hold to Tuesday close" did, but the net effect on return was roughly neutral to slightly negative on this data; the smaller position size (1.5% vs 2.5%) mechanically shrinks both wins and the worst loss's rupee share of capital slightly, without changing the underlying trade selection.

**Full weekly return ledger exported** per Suraj's request: `notes/backtests/range_strangle_v01_weekly_returns.csv` (95 traded weeks: date, sides, exit reasons, week P&L, week return %, cumulative equity, drawdown) and `range_strangle_v01_trade_pairs.csv` (full entry/exit detail per leg). Key read: **8 of 95 traded weeks were negative, and those 8 weeks alone total −₹51,525 — roughly 5x the eventual 5-year net gain.** One week (2023-W05, the flip-mechanism failure already documented above) is −₹24,789 by itself, about 2.3x the entire 5-year net profit — the single most consequential week in the whole backtest.

## Next

1. **Decide on wider strike data** — the hedged variant cannot be properly tested without it; this is now the binding constraint, not a strategy question.
2. Test the naked variant on a flatter/down-trending sub-period to see if the PE-side edge survives without the drift tailwind.
3. The flip rule is now implicated in the single worst week on record (2023-W05) as well as one of the next-worst (2024-W45, also breach_stop→premium_stop). Worth testing with the flip disabled entirely to isolate its contribution.
