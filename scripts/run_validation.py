#!/usr/bin/env python3
"""Run the data validation suite and print a summary.

Order matters: the expiry calendar is built first because iv_consistency
needs tau. Detail tables land in data/meta.duckdb; the printed summary is the
basis for notes/validation-report.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from pipeline import expiry_calendar, validate  # noqa: E402


def main() -> None:
    con = duckdb.connect()

    print("=== 1. expiry calendar (empirical) ===")
    cal = expiry_calendar.build(con)
    print(expiry_calendar.summary(cal))

    print("\n=== 2. bar integrity ===")
    bi = validate.bar_integrity(con)
    print(bi["distribution"].to_string(index=False))
    print(bi["day_mismatch"].to_string(index=False))

    print("\n=== 3. timestamp sanity ===")
    ts = validate.timestamp_sanity(con)
    print(ts["time_of_day"].to_string(index=False))
    print(f"duplicate (flag,type,offset,ts) keys: {ts['duplicates']}")

    print("\n=== 4. spot cross-check (option-embedded vs index, per minute) ===")
    print(validate.spot_crosscheck(con).to_string(index=False))

    print("\n=== 5. IV price-space consistency (weekly, offsets ±5, 15:15 bar) ===")
    iv = validate.iv_consistency(con)
    print(f"sampled options: {iv['n_total']:,}")
    print(iv["by_dte"].to_string(index=False))

    print("\n=== 6. ATM IV vs India VIX ===")
    print(validate.vix_check(con).to_string(index=False))


if __name__ == "__main__":
    main()
