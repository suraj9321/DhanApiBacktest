---
tags: [data, log]
date: 2026-07-17
---

# Validation Report — 5-Year Dataset

Part of [[Home]]. Pipeline: [[data-pipeline]]. Verdict: **PASS — dataset trusted for modeling**, with three documented exclusion rules. Detail tables in `data/meta.duckdb` (`validation_*`, `expiry_calendar`, `expiry_day_detail`). Rerun anytime: `.venv/bin/python scripts/run_validation.py`.

## Results

| # | Check | Result | Verdict |
|---|---|---|---|
| 1 | Expiry calendar (empirical) | 261 weekly + 60 monthly expiries; weekdays: 205 Thu / 42 Tue / 10 Wed / 4 Mon (weekly) | ✅ |
| 2 | Bar integrity | Sessions 375/376 bars; oddballs are real events (Muhurat ~60, special sessions ~105) | ✅ |
| 3 | Timestamp sanity | 0 duplicate keys in 38.8M rows; bars within legitimate session hours | ✅ |
| 4 | Spot cross-check | Option-embedded spot vs index series: p50 diff 0.0, p99 0.9 pts (0.0036%), max 23.9 | ✅ |
| 5 | IV price consistency | Reprice with API IV (Black-76 on parity forward, τ from calendar): median rel err 2–7% for dte 0–6 | ✅ (see note) |
| 6 | ATM IV vs India VIX | corr 0.60, ATM weekly IV ≈ VIX − 1.0 pts on average | ✅ plausible |

**IV note:** 2–7% price-space error reflects vendor IV smoothing + minute alignment; fine for signals and Greeks. **Traded prices, not IV-repriced values, remain the source of truth for P&L** in the backtester.

**VIX note:** 0.60 correlation is expected from the maturity mismatch (≤7-day ATM IV vs 30-day VIX) and the weekly IV sawtooth across expiries; a constant-maturity IV series (later) should correlate ~0.8+.

## Expiry detection: how it evolved (methodology record)

1. **v1 — absolute threshold** (straddle time value < 20 pts at last bar): missed 43 expiries — violent expiry days close with 20–120 pts of settlement uncertainty. Symptom was unmistakable: IV-consistency errors exploding at dte = 7, 14, 21, 28 (τ off by exactly one week).
2. **v2 — cadence argmin** (one expiry per ISO week / month, pick min TV): fixed 42 of 43; failed on the May 2025 India-Pakistan conflict week, where the true expiry (May 8, TV=120) lost the argmin to May 7 (TV=94).
3. **v3 — cadence + roll-jump (final):** the unfakeable signature is the *roll*: the session after expiry, the front contract gains ~a week of life and TV jumps several-fold (normal weeks 20–60×, war week 3.6×, non-expiry days ~1×). Argmax of `next_tv / tv` per period, accept if jump > 2. All 261 weekly + 60 monthly expiries correct; the sole dte=7 residual is genuinely correct (below).

## Anomalies investigated (all explained, none unresolved)

- **2025-05-08 (war week):** expiry-day ATM straddle held 120 pts at 15:29 — real settlement uncertainty during Operation Sindoor, not bad data. Drove the v2→v3 detector change.
- **2025-10-21 (Diwali):** expiry holiday-shifted to Mon Oct 20; the Oct 21 *Muhurat evening session* trades next week's contract (dte=7 is correct). Muhurat sessions are illiquid ceremonial sessions.
- **10 "missing" option days:** all Saturdays 2021–22 with 37–457 spot bars — NSE disaster-recovery/mock sessions captured by the index feed. Spurious spot data, not missing options data.

## Exclusion rules for all downstream analyses

1. **Exclude Saturday sessions** (DR/mock artifacts in spot data).
2. **Exclude Muhurat evening sessions** from trading logic (illiquid; wrong-week contract on the rolling front).
3. **Flag τ ≤ 15 min bars** (settlement window) — Greeks unstable there by construction.
4. **Filter zero rows from India VIX daily** — earliest rows (2007) carry 0.00 OHLC placeholders.
5. **Same-strike CE vs PE IVs differ materially** (e.g., 7 vs 11.5 in dividend periods) — the vendor IV appears spot-referenced with assumed carry, splitting the basis between call and put IVs. Our parity-forward Greeks absorb this; never treat the two legs' API IVs as one smile without forward-adjusting.
