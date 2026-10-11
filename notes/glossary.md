---
tags: [reference, glossary]
date: 2026-07-17
---

# Glossary — Options & Data-Validation Terms

Part of [[Home]]. Terms as used in [[validation-report]], [[data-pipeline]], and [[vrp-signals]]. Examples use Nifty ≈ 25000.

## Statistics (validation metrics)

- **Percentile (p50 / p90 / p99)** — The value below which that share of observations falls. p50 is the median ("typical"), p90 the tail ("only the worst 10% exceed this"). Used instead of the mean because error distributions are skewed by outliers. *Example: rel_err p50 = 0.02, p90 = 0.15 → typically 2% off, but 10% of rows are off by more than 15%.*
- **Absolute error (abs_err)** — |model price − market price| in rupees. *Example: model says ₹103, market ₹100 → abs_err ₹3.*
- **Relative error (rel_err)** — abs_err ÷ market price. *₹3 on ₹100 → 3%.* Denominator floored at ₹1 so tiny premiums don't produce meaningless huge percentages.
- **IQR band** — Interquartile range: the p25–p75 zone holding the middle 50% of observations; shaded around the mean line in [[analysis-theta-curve]]. Outlier-proof (unlike ±std), and its *width* is a signal — wide band = regime dependence. Note: 25% of real weeks lie above it and 25% below; it is a typical range, not an envelope.

## Prices, forwards, carry

- **Spot** — The current index level itself. *Nifty at 25000 now.*
- **Forward (price)** — Price agreed today to buy the index on expiry day, no cash until then. Arbitrage forces `forward = spot + carry`. *Weekly Nifty forward ≈ 25006–25020.*
- **Carry (cost of carry)** — Net cost of holding a position: interest paid (or foregone) minus dividends received. Positive carry pushes the forward above spot; heavy dividends can flip it negative. *25000 × 6.5% × 5/365 ≈ 22 pts interest − dividends ≈ +18 pts/week.* Broader usage: what a position earns per day if nothing moves — for a short option, carry = theta.
- **Basis** — Forward (or futures) minus spot; the market-observed carry. *Our data: p50 +6.4 pts weekly, +39.6 monthly — scales with time as carry should.*
- **Put-call parity** — Long call + short put (same strike) replicates a forward struck at K, so `C − P = F − K`, giving the **parity forward** `F = K + C − P` read directly from ATM option prices. Absorbs whatever carry the market is actually charging — no rate/dividend assumptions.
- **Black-76** — Variant of Black-Scholes that prices options off the **forward** instead of spot, folding rates and dividends into one observed input. Our repricing model in validation check #5.

## Implied volatility

- **Implied volatility (IV)** — The volatility that makes the model price equal the market price; found numerically (no closed form). It is the market price *translated into volatility units*, not a measurement. *25000 CE @ ₹90, 3 dte → solver finds σ = 12.2%.* Inherits the computer's assumptions — Dhan's assumed carry is why same-strike CE/PE API IVs differ ([[validation-report]] caveat).
- **Volatility smile** — Plot of IV vs strike for one expiry: lowest ATM, rising toward both wings. Exists because real returns have fat tails and crash risk that flat-IV lognormal pricing ignores.
- **Skew / smirk** — The smile's asymmetry: OTM put IVs > OTM call IVs for indices (crash fear + hedging demand). *Why an iron condor's put spread collects more credit than the equidistant call spread.*
- **India VIX** — NSE's 30-day expected-volatility index computed from option prices. Our ATM weekly IV ≈ VIX − 1 pt, corr 0.60 (maturity mismatch explains the gap).
- **VRP (volatility risk premium)** — The tendency of implied vol to exceed subsequently realized vol; the structural edge an option seller harvests. *IV 13% vs realized 10% → 3 vol pts of premium collected for bearing tail risk.*

## Option contract basics

- **CE / PE** — NSE ticker suffixes: CE = call (right to buy), PE = put (right to sell).
- **Strike (K)** — The level the option's payoff is measured against. *25000 CE pays max(0, Nifty − 25000) at expiry.*
- **Strike offset** — Strike distance from ATM in strike-step units; our data uses −10…+10. *Offset +2 with 50-pt steps → 25100.*
- **ATM / OTM / ITM** — At/out-of/in-the-money: strike at, beyond, or inside the current index level. *Nifty 25000: the 25000 straddle is ATM; 25500 CE and 24500 PE are OTM.*
- **Premium** — The option's traded price. Splits into **intrinsic value** (payoff if exercised now, max(0, S−K) for a call) + **time value** (the rest — the price of remaining uncertainty). *Nifty 25080: 25000 CE @ ₹115 = 80 intrinsic + 35 time value.*
- **Expiry / settlement** — Last day the contract lives; cash-settled at 15:30 vs the closing index level. **dte** = calendar days to expiry; **τ (tau)** = same thing in years, the model input. *3 dte → τ ≈ 3.01/365.*
- **Straddle** — CE + PE at the same (ATM) strike. Its price is a pure read on expected movement, so its **time value collapsing to ~0 at the close is the expiry signature** used by our detector. *War week exception: 120 pts of settlement uncertainty at 15:29.*
- **Iron condor** — Sell an OTM call spread + OTM put spread: collect premium, profit if the index stays in a range, losses capped by the bought wings.
- **Roll** — The front (nearest-expiry) contract switching to the next expiry after settlement. Signature: time value jumps several-fold next session (20–60× normal, 3.6× war week) — the "unfakeable" expiry marker in detector v3.

## Greeks (model sensitivities)

- **Delta (Δ)** — Price change per 1-pt index move; also ≈ probability of expiring ITM. *ATM ≈ +0.5 (CE) / −0.5 (PE); sanity check: Δc − Δp ≈ 1.*
- **Theta (θ)** — Price change per day from time passing; negative for the buyer, income for the seller. *Straddle @ ₹180 with 2 dte loses ~₹40–50/day standing still.*
- **Vega** — Price change per 1 vol-pt change in IV. *IV 12→13% moves an ATM weekly ≈ its vega, a few rupees.*

## Market calendar / data events

- **Muhurat trading** — NSE's ~1-hour ceremonial Diwali evening session; illiquid, and on a rolling front series it trades *next* week's contract. Excluded from trading logic.
- **DR / mock session** — NSE disaster-recovery drills, typically Saturdays; index feed captures spurious bars, options don't trade. Excluded.
- **Holiday shift** — An expiry landing on a holiday moves to the previous trading day. *Diwali Tue 2025-10-21 → expiry Mon 2025-10-20.*
