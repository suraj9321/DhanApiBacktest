#!/usr/bin/env python3
"""Data pipeline orchestrator.

Usage:
  python scripts/pull_all.py --probe     # tiny test calls; verify token, IDs, shapes
  python scripts/pull_all.py --options   # 5y rolling options (resumable)
  python scripts/pull_all.py --spot      # Nifty + VIX, daily since inception + 5y intraday
  python scripts/pull_all.py --parquet   # rebuild parquet from raw cache (offline)
  python scripts/pull_all.py --all       # everything above, in order
  python scripts/pull_all.py --status    # cache + parquet inventory (offline)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pipeline import config, fetch_options, fetch_spot, to_parquet  # noqa: E402
from pipeline.dhan_client import DhanClient  # noqa: E402


def status() -> None:
    n_raw = sum(1 for _ in config.RAW_DIR.rglob("*.json")) if config.RAW_DIR.exists() else 0
    print(f"raw cache: {n_raw} response files under {config.RAW_DIR}")
    pq = list(config.PARQUET_DIR.rglob("*.parquet"))
    print(f"parquet: {len(pq)} files under {config.PARQUET_DIR}")
    if pq:
        import duckdb

        con = duckdb.connect()
        opt_glob = str(config.PARQUET_DIR / "options" / "*" / "*" / "*.parquet")
        try:
            n, lo, hi = con.execute(
                f"SELECT count(*), min(ts), max(ts) FROM read_parquet('{opt_glob}')"
            ).fetchone()
            print(f"options rows: {n:,}  span: {lo} .. {hi}")
        except duckdb.Error:
            print("options parquet: none yet")
        spot_glob = str(config.PARQUET_DIR / "spot" / "*" / "*" / "*.parquet")
        try:
            (n,) = con.execute(
                f"SELECT count(*) FROM read_parquet('{spot_glob}')"
            ).fetchone()
            print(f"spot rows: {n:,}")
        except duckdb.Error:
            print("spot parquet: none yet")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--options", action="store_true")
    p.add_argument("--spot", action="store_true")
    p.add_argument("--parquet", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    if args.status:
        status()
        return
    if args.parquet and not (args.all or args.options or args.spot or args.probe):
        to_parquet.build_options()
        to_parquet.build_spot()
        return

    config.assert_token()
    client = DhanClient()

    if args.probe or args.all:
        fetch_options.probe(client)
        fetch_spot.probe(client)
    if args.options or args.all:
        fetch_options.pull(client)
    if args.spot or args.all:
        for name in ("nifty", "indiavix"):
            fetch_spot.pull_daily(client, name)
            fetch_spot.pull_intraday(client, name)
    if args.parquet or args.all:
        to_parquet.build_options()
        to_parquet.build_spot()
    if not any(vars(args).values()):
        p.print_help()


if __name__ == "__main__":
    main()
