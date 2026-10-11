---
tags: [data, infra]
---

# Data Pipeline

Part of [[Home]]. Feeds the signals in [[vrp-signals]] and the backtester implied by [[adjustment-policy]]. API details: [[dhan-api-docs]].

## Data requirements, mapped to the Dhan API

| Need | Source | Status |
|---|---|---|
| Historical option minute bars: OHLC, IV, OI, volume, spot | `POST /charts/rollingoption` — 5 yr, ATM±10 strikes, ≤45 days/call, WEEK + MONTH | ✅ covered |
| Nifty index daily OHLC, **from inception (~20 yr)** | `POST /charts/historical`, `IDX_I` segment | ✅ covered |
| Nifty index intraday 1-min, 5 yr | `POST /charts/intraday`, `IDX_I` segment (chunked calls) | ✅ covered |
| India VIX (daily + intraday) | attempt via `IDX_I` (find security ID in instrument master) | ⚠️ verify |
| Expiry calendar | `/optionchain/expirylist` + static rules | ✅ covered |
| Live chain w/ greeks, bid/ask | `POST /optionchain` (3s rate limit) | ✅ for live phase |
| Margin per structure | `/margincalculator/multi` | ✅ for sizing |
| Event calendar (RBI/Fed/budget) | external — maintain a small static table | manual |
| Cost model (STT, txn charges, slippage) | we build it — see [[risk-framework]] | ours to write |
| Nifty futures (basis/carry) | deferred — second-order for index option backtests | later |

## Why independent underlying data (not just the `spot` field in option responses)

The option-embedded spot is aligned to option bars — right for trade simulation, wrong for vol modeling:

1. **Sample size.** GARCH(1,1) on 5 yr (~1,250 daily obs) is unstable; ~20 yr (≈5,000 obs incl. 2008, taper tantrum, COVID) makes the weekly-move distribution and tail estimates trustworthy. Tails are where each extra year has the highest marginal value.
2. **Independence for validation.** Cross-checking embedded spot vs. the index series catches data defects a single source cannot reveal about itself.
3. **Completeness.** Embedded spot inherits option-trading gaps; the index series is gapless within sessions.

**What each dataset unlocks:** daily/20yr → GARCH, weekly-move distribution, 20-yr Fri→Mon gap stats (black-swan sizing for [[trade-window]]). Intraday/5yr → HAR-RV (RV from 5-min returns), overnight-vs-intraday variance split (prices the weekend hold directly), jump detection (bipower variation), and ex-post realized vol per historical entry — the ground truth that scores every [[vrp-signals]] Tier-1 signal.

> [!note] Known data limitation
> Rolling options data covers **ATM±10 strikes = ±500 points**. On Nifty at ~25,000 that's ±2%. In high-IV weeks, 10Δ strikes can sit outside that window — and the far wings often will. The backtest may need to price wings via Black-Scholes from the IV surface edge rather than observed quotes. Acceptable (wings are small premium), but it must be done honestly.

## Storage design (approved 2026-07-17)

**Parquet (data at rest) + DuckDB (query engine), decoupled.** Full reasoning discussed 2026-07-17; essentials: pure OLAP workload (write-once minute bars, column scans, no point updates) → columnar layout; Parquet = engine-agnostic, compressed, zone-map pushdown; DuckDB = embedded, vectorized, `ASOF JOIN`, queries Parquet in place, zero ops, S3-ready for the AWS phase. Bulk bars in Parquet; mutable bookkeeping (fetch progress, validation results, calendars) in `data/meta.duckdb`.

**Partitioning (revised from the first sketch):** options partitioned by `flag=week|month / month=YYYY-MM`, rows sorted by `(option_type, strike_offset, ts)` within files — directory pruning handles the date range, zone maps handle strikes. NOT partitioned by expiry: expiry assignment needs the exact NSE holiday calendar, and a calendar error would misfile rows at the storage layer. An expiry week of a rolling series is just a time-range filter; a later enrichment step adds `expiry_date` as a column (errors = correctable updates, not misfiled files). Also avoids the small-files problem (~310 partitions of MBs vs ~13,000 tiny files under per-strike partitioning). Spot: partitioned by year.

## Fetcher (built 2026-07-17)

Code in `src/pipeline/`, orchestrated by `scripts/pull_all.py`:

- `config.py` — all tunables; secrets from `.env` (gitignored; `.env.example` provided).
- `dhan_client.py` — throttled (3 rps vs the 5 rps Data-API limit), retries with exponential backoff on 429/5xx, fail-fast on 401, and **raw-response disk cache** keyed by request identity → every pull is resumable and idempotent; atomic cache writes survive crashes.
- `fetch_options.py` — WEEK+MONTH × ATM±10 × 45-day windows; `probe()` resolves two documented ambiguities empirically before the big pull (whether one call returns both CE+PE — halves the calls if so — and strike-offset semantics).
- `fetch_spot.py` — Nifty + India VIX: daily since inception, 1-min intraday 5y in 75-day chunks; VIX security ID verified by probe, tolerated if absent.
- `to_parquet.py` — raw JSON → partitioned Parquet per the layout above; full rebuild from raw is idempotent (raw stays the source of truth).

Usage: `--probe` (verify assumptions, ~4 calls) → `--options` → `--spot` → `--parquet`; `--status` for inventory; `--all` for everything.

## Enrichment stage: Greeks (added 2026-07-17)

The historical API serves prices + IV only — Greeks are **derived, not fetched** (better: we control the convention and can regenerate). Enrichment writes additional Parquet columns: `expiry_date`, `tau`, `implied_fwd`, `delta`, `gamma`, `theta`, `vega`.

- **Uses:** delta → strike selection (10–15Δ), adjustment triggers (Δ>25–30 in [[adjustment-policy]]), prob-of-touch ≈ 2Δ; gamma → near-expiry risk (the exit logic in [[vrp-signals]] is a gamma statement); theta → P&L decomposition for the weekend-capture study in [[trade-window]]; vega → IV-shock and margin-expansion stress in [[risk-framework]].
- **Forward via put-call parity:** with CE+PE at every strike/timestamp, `F ≈ K + (C − P)` (discounting negligible ≤7 days) — Greeks priced off the market's own forward; no r/q assumptions. Fallback: spot + assumed carry where pairs are missing.
- **Precomputed as columns** (one vectorized pass over 38.8M rows, ~+200 MB) rather than recomputed inside every backtest loop.
- **Cautions:** Greeks inherit API IV → IV validation must pass first; τ→0 explosion near expiry → τ floor + flag, never confident garbage.

### Built 2026-07-17 (`src/pipeline/enrich.py`, run: `scripts/run_enrichment.py`)

`data/parquet/options_enriched/` mirrors the base partitioning, adds: `expiry_date`, `tau` (ACT/365, bar-close→15:30 IST settlement, 5-min floor), `fwd` (per-minute parity forward, day-median-basis fallback), `delta` (forward delta), `gamma`, `vega` (per vol-pt), `theta_day`, `settlement_window` (τ≤15min), `special_session` (Muhurat). Black-76, r=0 — same convention validation certified.

**Sanity results:** ATM deltas 0.51/−0.48 (weekly) and 0.54/−0.46 (monthly — larger carry, correct); Δc−Δp = 0.989±0.047 (per-leg smile IVs); basis p50 +6.4 pts weekly / +39.6 monthly (cost-of-carry scaling ✓); theta < 0 on 100% of computed rows. **Null Greeks 4–9%**, fully explained: monotone in |offset| (0.6% ATM → 14–23% at ±10) = untraded far-OTM minutes with no IV; zero unexplained nulls. Backtest implication: far-wing valuation needs last-known-value carry or smile interpolation over gap minutes.

## Build order

1. **Data pipeline** — pull 5 yr rolling options + spot into Parquet/SQLite (45-day chunks × ~40 windows × strikes × CE/PE; hours of rate-limited calls).
2. **Vol-metrics library** — RV estimators, IV surface, VRP series.
3. **Event-driven backtester** with full per-leg cost model.
4. **Strategy grid + walk-forward validation.**
5. **Paper trading** against the live chain.
6. **Go live** with 1–2 lots.
