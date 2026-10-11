---
tags: [moc]
---

# Nifty Weekly Option Selling — Home

**Capital:** ₹8L to start, scaling to ₹20L
**Mandate:** Systematic option selling on Nifty weekly expiry, always hedged against black-swan events, entries/exits driven by mathematical signals.

## Map of content

- [[strategy-overview]] — the VRP thesis, why iron condors, India-specific market facts, honest return expectations
- [[vrp-signals]] — entry signal tiers and exit logic
- [[trade-window]] — Friday → Tuesday holding window analysis
- [[adjustment-policy]] — state-machine rules for adjusting and resizing
- [[data-pipeline]] — data requirements, Dhan API mapping, build order
- [[vol-metrics]] — RV forecasters, parity-consistent IV, constant-maturity series, the measured VRP (+1.6 pts mean)
- [[risk-framework]] — capital structure, layered loss limits, cost model, event-week policy
- [[validation-report]] — dataset validation results, expiry-detection methodology, exclusion rules
- [[analysis-weekend-gaps]] — Fri→Mon gap distribution (20y): tails, asymmetry, wing-sizing consequences
- [[analysis-weekend-theta]] — weekend theta capture ≈ **zero** unconditionally; verdict flips default entry to Monday morning
- [[analysis-theta-curve]] — decay curves weekly vs monthly (chart): last session holds 57% of weekly decay; monthly early weeks drip 3–8× slower
- [[analysis-monday-entry]] — **strategy v0.1 candidate**: T−1 09:20 → expiry 13:15 shows +16 pts/wk unconditional (t≈2.5), first positive segment found
- [[analysis-greeks-curves]] — gamma/vega/theta/delta through the cycle (chart): θ∝Γ twins, monthly = vega trade, delta-based strikes auto-adapt
- [[architecture-backtester]] — event-driven backtester design spec (diagram, components, test plan)
- [[decisions-log]] — dated record of decisions taken
- [[conversation-log]] — verbatim discussion transcripts
- [[dhan-api-docs]] — full Dhan API reference (large)

### External references

- [[ref-theta-gainers-iron-condor]] — distilled monthly iron-condor→iron-fly strategy (Reyaansh Upadhyay) with critical assessment and extracted backtest hypotheses
- [[ref-theta-gainers-transcript]] — raw interview transcript

Future folders: `journal/` (one note per trade week), `backtests/` (one note per backtest run).

## Current status (2026-07-17, end of day)

**Dataset on disk.** Full 5-year pull complete (3,444 option windows, 0 empty; 884 MB Parquet, 3.1 GB raw cache):

- Options: **38.8M minute bars**, 2021-07-19 → 2026-07-16, weekly + monthly, ATM±10, CE+PE balanced. Early sanity signals look right: PE IV > CE IV (index put skew), weekly IV > monthly (expiry-week effect), bar counts per day match NSE sessions (375/376 full days, 60-bar Muhurat sessions).
- Nifty spot: daily 2006→now (5,090 bars), 1-min intraday 2021→now (528k bars).
- India VIX: daily 2007→now (4,614 bars), 1-min intraday 2021→now (526k bars) — real VIX, no proxy needed.

**Validation: PASS** (2026-07-17, see [[validation-report]]) — empirical expiry calendar built (261 weekly + 60 monthly), all five checks green, three exclusion rules documented (Saturdays, Muhurat, τ≤15min).

**Greeks enrichment: DONE** (2026-07-17) — `options_enriched` dataset with expiry_date, τ, parity forward, delta/gamma/vega/theta + session flags; all sanity checks textbook (see [[data-pipeline]]).

**Vol-metrics library: DONE** (2026-07-17, see [[vol-metrics]]) — VRP measured at +1.6 vol pts mean, positive every year.

**Backtester: BUILT** (2026-07-18, [[architecture-backtester]]) — event-driven engine, money-math unit-tested to the rupee, invariants passing. First full run: [[run-2026-07-18-weekly-v01]] — **v0.1 condor is NEGATIVE after costs** (−3.7%/5y; costs = 41% of gross wins; delta-breach exits too twitchy). Follow-up fly series ([[run-2026-07-18-fly-series]]): **first green run** — z-band-gated fly +6.7%/5y, Sharpe 0.40, maxDD −4.5% — with a scientifically important inversion found (high vrp_z weeks are adverse; gate is a band, not a floor). In-sample caveat: **walk-forward validation is the next step** before anything is believed.

**Two new variants explored (2026-07-19/20):** [[run-2026-07-19-expiry-day-condor]] — expiry-day-only ("0DTE") condor sized to the market's own expected-move, every configuration tested stayed negative (−5% to −17%/5y). [[run-2026-07-20-range-strangle]] — naked range-breakout strangle (Suraj's explicit, temporary deviation from hedged-only, stop-loss risk control instead): +1.82%/5y, Sharpe 0.21, thin edge carried almost entirely by the put side (index drift tailwind), two of five years net negative. **Hedged follow-up same day: BLOCKED by a data-coverage wall**, not a strategy result — our ATM±10 strike pull is fixed in strike *count*, so as Nifty's price rose over the window the achievable wing room collapsed to **zero for all of 2025–2026**. Wider strike data is now the binding next decision before the hedged variant can be evaluated at all.
