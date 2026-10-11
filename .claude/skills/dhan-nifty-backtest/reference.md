# Backtest run log template

Create `notes/backtests/run-YYYY-MM-DD-<short-name>.md`:

```markdown
---
tags: [backtest, log]
date: YYYY-MM-DD
---

# Backtest: <config name> — one-line verdict

Part of [[Home]] · config `configs/<name>.yaml` · ledgers `data/backtest_<name>_*.parquet`.

## Config summary
(entry DTE/time, structure, gates, exits, sizing — bullet list)

## Result
| Metric | Value |
|--------|-------|
| Total return | |
| Sharpe | |
| Max DD | |
| Trades / win% | |
| Costs vs gross wins | |

## Diagnosis
1. …
2. …

## Caveats
(in-sample gates, thin n, data fallbacks, margin/slippage placeholders)

## Next
- …
```

Link related notes: `[[run-…]]`, `[[vrp-signals]]`, `[[data-pipeline]]`.

## Agent workflow with the vault

- Open/attach `notes/Home.md` or `notes/backtests/` when scoping a task so the agent inherits mandate and past failures.
- Before changing `src/backtest/risk.py` or sizing, read `notes/risk-framework.md`.
- Wikilinks are what agents follow in plain text; Obsidian graph view is optional for humans.

## Known result anchors (do not treat as gospel)

| Config | 5y headline | Note |
|--------|-------------|------|
| `weekly_v01` | −3.7% | Cost + delta_breach |
| `weekly_fly_zband` | +6.7% | z-band gate; walk-forward pending |
| `range_strangle_v01` | +1.8% | Naked; put-side drift |

Refresh numbers from a new run before citing in README or vault.
