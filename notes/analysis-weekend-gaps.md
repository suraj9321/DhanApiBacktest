---
tags: [analysis, risk]
date: 2026-07-17
---

# Analysis 1: Weekend Gap Distribution (Nifty, 2006–2026)

Part of [[Home]]. Sizes the unadjustable risk of the Fri→Tue window in [[trade-window]]; feeds wing sizing in [[risk-framework]]. Reproduce: `.venv/bin/python scripts/analyze_gaps.py` (daily spot, 941 weekends over ~20y).

## Distribution (Fri close → Mon open, %)

| Sample | n | sd | p01 | p50 | p99 | min | max |
|---|---|---|---|---|---|---|---|
| Full 20y | 941 | 0.67 | −2.12 | +0.05 | +1.61 | **−9.14** | +3.58 |
| Recent 5y | 231 | 0.75 | −2.26 | +0.09 | +1.61 | −5.00 | +3.58 |

Tail frequencies (weekends + long weekends, full history / recent 5y):

| Threshold | 20y | Recent 5y |
|---|---|---|
| \|gap\| > 1% | 1 in 12 | 1 in 9 |
| \|gap\| > 2% | 1 in 48 | 1 in 32 |
| \|gap\| > 3% | 1 in 151 | 1 in 130 |
| \|gap\| > 5% | 1 in 529 | 1 in 259 |

Worst events: **−9.14%** (Covid, Mar 2020), **−5.00%** (tariff crash, Apr 2025), −3.69% (Mar 2020), +4.48% (Apr 2020), **+3.58% (election exit polls, Jun 2024)**. At Nifty ~24,000: p01/p99 ≈ −510/+400 points; worst observed ≈ −2,200 points.

## Key findings

1. **Weekend variance ≈ 1.8× a single overnight** (sd 0.67 vs 0.50), not 3× — closed days contribute far less than pro-rata variance. The market genuinely "sleeps"; MMs' Friday IV markdown has a real basis. Quantifies the [[trade-window]] caveat.
2. **The tail is asymmetric — crashes gap down:** five of the seven worst gaps are negative. The put side carries the catastrophe risk; the call side's worst case (~+3.6–4.5%) is meaningful but smaller.
3. **Ordinary adjustment-trigger events are common:** >2% gaps happen ~1-in-32 weekends (recent era) — roughly once a year. These reach a 15Δ short strike but are a Monday-morning adjustment scenario, not account damage.
4. **Catastrophes are rare but fully in-sample:** two >5% down-gaps in 20 years, one of them (Apr 2025) inside our options dataset — the backtest will price it with real option prices.
5. **Recent 5y tails are fatter than the 20y average** — the options era is not a calm sample; no optimism discount needed.

## Strategy consequences

- **Wing width is the only control that works at −9%.** Stops and adjustments don't execute through a gap. Structural bound (layer 4 of [[risk-framework]]): wings must cap the portfolio loss at ≤ ~8% of capital *assuming a −9% Monday open*, i.e., all short puts at max depth. Sizing must use wing width, never gap-conditional hopes.
- **Put wings deserve to be closer than call wings** (asymmetric tail) — candidate rule for the backtest grid: put wing at ~1.5–2× the call wing's distance budget.
- **Expectancy math must charge each weekend** ~1/32 odds of an adjustment event and ~1/150 odds of a tail event against the ~35–40 pts of weekend theta observed in the sample decay curve. Whether that trade nets positive is exactly Analysis 2 (weekend theta capture).
