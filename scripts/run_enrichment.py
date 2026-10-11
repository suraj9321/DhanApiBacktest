#!/usr/bin/env python3
"""Build the Greeks-enriched options dataset, then run sanity checks on it."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from pipeline import enrich  # noqa: E402


def sanity() -> None:
    con = duckdb.connect()
    glob = str(enrich.ENRICHED_DIR / "*" / "*" / "*.parquet")
    q = f"read_parquet('{glob}', hive_partitioning=true)"

    print("\n--- sanity: ATM delta should straddle 0.5/-0.5 ---")
    print(con.execute(f"""
        SELECT flag, option_type, round(avg(delta),3) avg_delta,
               round(quantile_cont(delta,0.5),3) med_delta, count(*) n
        FROM {q} WHERE strike_offset=0 AND NOT settlement_window AND delta IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """).fetchdf().to_string(index=False))

    print("\n--- sanity: put-call delta parity (dc - dp = 1) ---")
    print(con.execute(f"""
        WITH ce AS (SELECT ts, strike_offset, delta FROM {q} WHERE option_type='CE' AND flag='week'),
             pe AS (SELECT ts, strike_offset, delta FROM {q} WHERE option_type='PE' AND flag='week')
        SELECT round(avg(ce.delta - pe.delta),4) AS avg_dc_minus_dp,
               round(stddev(ce.delta - pe.delta),4) AS sd
        FROM ce JOIN pe USING (ts, strike_offset)
        WHERE ce.delta IS NOT NULL AND pe.delta IS NOT NULL
    """).fetchdf().to_string(index=False))

    print("\n--- sanity: forward basis (fwd - spot), points ---")
    print(con.execute(f"""
        SELECT flag, round(quantile_cont(fwd-spot,0.5),1) p50,
               round(quantile_cont(fwd-spot,0.05),1) p05,
               round(quantile_cont(fwd-spot,0.95),1) p95
        FROM {q} WHERE strike_offset=0 AND option_type='CE'
        GROUP BY 1 ORDER BY 1
    """).fetchdf().to_string(index=False))

    print("\n--- sanity: theta sign & coverage ---")
    print(con.execute(f"""
        SELECT flag,
               round(100.0*count(*) FILTER (WHERE theta_day < 0)/count(*) FILTER (WHERE theta_day IS NOT NULL),2) pct_theta_negative,
               round(100.0*count(*) FILTER (WHERE delta IS NULL)/count(*),2) pct_greeks_null,
               round(100.0*count(*) FILTER (WHERE settlement_window)/count(*),2) pct_settle_window,
               round(100.0*count(*) FILTER (WHERE special_session)/count(*),3) pct_muhurat
        FROM {q} GROUP BY 1 ORDER BY 1
    """).fetchdf().to_string(index=False))


def main() -> None:
    enrich.build()
    sanity()


if __name__ == "__main__":
    main()
