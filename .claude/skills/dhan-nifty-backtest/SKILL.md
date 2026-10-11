---
name: dhan-nifty-backtest
description: >-
  Runs and extends the DhanApiBacktest stack: DhanHQ data pull, Parquet pipeline,
  Greeks/signals, YAML iron condor/fly backtests, and Obsidian run logs. Use when
  working in DhanApiBacktest, Nifty option backtests, VRP gates, run_backtest.py,
  configs/*.yaml, src/backtest/, notes/backtests/, or Dhan rolling options data.
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(.venv/bin/python scripts/run_backtest.py:*)
  - Bash(.venv/bin/python scripts/run_validation.py:*)
  - Bash(.venv/bin/python scripts/run_enrichment.py:*)
  - Bash(.venv/bin/python scripts/build_vol_metrics.py:*)
  - Bash(.venv/bin/python scripts/plot_backtest.py:*)
  - Bash(.venv/bin/python scripts/backtest_report.py:*)
  - Bash(.venv/bin/python scripts/run_range_strangle.py:*)
  - Bash(.venv/bin/python scripts/run_pivot_supertrend.py:*)
  - Bash(.venv/bin/python scripts/run_expiry_condor_v2.py:*)
  - Bash(.venv/bin/python scripts/pull_all.py:*)
  - Bash(.venv/bin/python -m pytest:*)
  - Bash(.venv/bin/pytest:*)
---

# Dhan Nifty backtest

## First reads (context brain)

Before changing strategy, sizing, or data assumptions:

1. `notes/Home.md` — current status and map of content
2. `notes/risk-framework.md` — loss layers, costs, sizing
3. `notes/architecture-backtester.md` — event loop, anti-look-ahead
4. Relevant prior run in `notes/backtests/` if the idea was tried before

Parquet holds numbers; `notes/` holds mandate, dead ends, and interpretation. Prefer updating both after a meaningful run.

## Hard constraints

- **Secrets:** `.env` only — never commit or paste tokens; never put credentials in `notes/`.
- **Look-ahead:** Strategies use `signals.as_of(d)` (T−1 EOD wall). Decide on bar *t*, fill at *t+1*.
- **Structures:** Main engine (`src/backtest/`) models **hedged** iron condor / iron fly only. Naked legs require an explicit user decision and usually a separate script (`range_engine`, pivot runner, etc.).
- **Costs:** All fills use `src/backtest/costs.py` — do not duplicate fee math elsewhere.
- **Sizing:** Fixed **1 lot (75)** per the project convention — no risk-% or multi-lot sizing unless the user explicitly asks.
- **Data coverage:** Options pull is **ATM±10** strike offsets; far wings and range-bound shorts may hit quote gaps — check `notes/data-pipeline.md` before claiming a hedged variant works.
- **Trust:** Report in-sample caveats; walk-forward is required before treating a gate as validated.

## Pipeline → backtest (happy path)

```text
- [ ] .env filled (DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID)
- [ ] .venv/bin/python scripts/pull_all.py --probe
- [ ] pull_all --options / --spot (or --all)
- [ ] pull_all --parquet
- [ ] scripts/run_validation.py
- [ ] scripts/run_enrichment.py
- [ ] scripts/build_vol_metrics.py
- [ ] scripts/run_backtest.py configs/<name>.yaml [start] [end]
- [ ] pytest tests/test_backtest_math.py (after engine/cost changes)
- [ ] scripts/plot_backtest.py <name>
- [ ] New or updated note in notes/backtests/
```

Use `.venv/bin/python` from repo root. `data/` is gitignored (raw JSON, Parquet, ledgers).

## Run a standard backtest

```bash
.venv/bin/python scripts/run_backtest.py configs/weekly_fly_zband.yaml
.venv/bin/python scripts/plot_backtest.py weekly_fly_zband
```

- Capital default: **₹8L** (`scripts/run_backtest.py`).
- Default window: **Tuesday-expiry regime** (from 2025-08-29) unless the user asks to go further back.
- Outputs: `data/backtest_<name>_trades.parquet`, `data/backtest_<name>_equity.parquet`.
- New variant: copy nearest YAML under `configs/`, change `name:` (must match ledger prefix), adjust gates/strikes/exits per `notes/vrp-signals.md`.

## Report after a run (project convention)

After every backtest, publish a browser HTML dashboard (equity / weekly-monthly / trade analytics):

```bash
.venv/bin/python scripts/backtest_report.py data/backtest_<name>_trades.parquet "<title>"
```

## Alternate runners (different trade shapes)

| Script | When |
|--------|------|
| `run_range_strangle.py` | Independent-leg range strangle (`src/backtest/range_engine.py`) |
| `run_pivot_supertrend.py` | Intraday pivot + Supertrend ATM shorts |
| `run_expiry_condor_v2.py` | Expiry-day expected-move condor grid |
| `backtest_report.py` | HTML dashboard from a trades parquet |

These reuse `MarketData` + `costs.py` but are not the main `Backtest` engine.

## After a run (required for research continuity)

1. Capture metrics from CLI (`metrics.print_report`) into a vault note — template in [reference.md](reference.md).
2. Diagnose *mechanism* (costs, exit mix, gate buckets), not only headline return.
3. If a signal rule changed, update `notes/vrp-signals.md` or `notes/decisions-log.md`.
4. Optional: PNG → `notes/attachments/`; link from note via `![[backtest-<name>.png]]`.

## Code map (where to edit)

| Area | Path |
|------|------|
| Fetch / Parquet | `src/pipeline/`, `scripts/pull_all.py` |
| Engine loop | `src/backtest/engine.py` |
| YAML strategy | `src/backtest/strategy.py`, `configs/` |
| Quotes / calendar | `src/backtest/data.py` |
| Structures | `src/backtest/structures.py` |
| Unit tests (money math) | `tests/test_backtest_math.py` |

Match existing style; minimal diffs. Do not over-engineer one-off grid knobs — prefer YAML + a short backtest note.

## README / GitHub

Summaries and architecture live in root `README.md`. Update results tables or charts only when the user wants public-facing docs refreshed.

## More detail

- Backtest log note template, tagging: [reference.md](reference.md)
