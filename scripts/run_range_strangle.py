#!/usr/bin/env python3
"""Run the range-breakout strangle: python scripts/run_range_strangle.py configs/range_strangle_v01.yaml [start] [end]"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtest.metrics import compute, print_report  # noqa: E402
from backtest.range_engine import RangeStrangleBacktest, RangeStrangleConfig  # noqa: E402

CAPITAL = 800_000


def main() -> None:
    cfg = RangeStrangleConfig.load(sys.argv[1])
    start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    end = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
    bt = RangeStrangleBacktest(cfg, CAPITAL, start, end)
    result = bt.run()
    m = compute(result, CAPITAL)
    print_report(cfg.name, m)
    out = Path("data") / f"backtest_{cfg.name}_trades.parquet"
    if len(result["trades"]):
        result["trades"].to_parquet(out, index=False)
        result["equity"].to_parquet(Path("data") / f"backtest_{cfg.name}_equity.parquet", index=False)
        print(f"\nledgers -> {out} (+equity)")


if __name__ == "__main__":
    main()
