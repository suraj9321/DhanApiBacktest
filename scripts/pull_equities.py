"""Download 5-year daily OHLC for the Nifty 100 (≈ the 100 most liquid large
caps) for backtesting — the same 5-year window as the rest of the project's data.

Pattern mirrors the existing pipeline: /charts/historical in 4-year chunks,
every response cached to data/raw/equities/<sym>/ before parsing (resumable +
idempotent), DH-907 "no data" windows skipped. Then parquet per symbol.

CAVEATS baked into the output report:
  • Survivorship bias — this is TODAY's liquid set, not point-in-time membership
    (mild over 5y, but names that de-listed / fell out of the top-100 are absent).
  • Corporate-action adjustment — flags per-symbol single-day jumps >40% that
    signal an UNADJUSTED split/bonus series (would corrupt backtests).

Usage:
  python scripts/pull_equities.py --limit 4        # validate on a few symbols
  python scripts/pull_equities.py                  # full Nifty 100 pull + parquet
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from liquidity_scorecard import load_scrip_master, resolve
from depth_scorecard import NIFTY50, NEXT50
from src.pipeline import config
from src.pipeline.dhan_client import DhanAPIError, DhanClient

EQUITIES_START = date.today() - timedelta(days=5 * 365)   # 5y, matches project window
CHUNK_DAYS = 4 * 365
RAW = config.RAW_DIR / "equities"
OUT = config.PARQUET_DIR / "equities" / "daily"
UNIVERSE = list(dict.fromkeys(NIFTY50 + sorted(set(NEXT50))))   # ~100, de-duped, ordered


def _payload(sec_id, frm, to):
    return {"securityId": str(sec_id), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
            "fromDate": frm.isoformat(), "toDate": to.isoformat()}


def _frame(body):
    ts = body.get("timestamp") or []
    if not ts:
        return None
    return pd.DataFrame({
        "ts": pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata"),
        "open": body.get("open"), "high": body.get("high"), "low": body.get("low"),
        "close": body.get("close"), "volume": body.get("volume"),
    })


def pull_symbol(client, sym, sec_id):
    frames, end = [], date.today()
    cur = EQUITIES_START
    while cur < end:
        stop = min(cur + timedelta(days=CHUNK_DAYS), end)
        path = RAW / sym / f"{cur.isoformat()}_{stop.isoformat()}.json"
        try:
            body, _ = client.cached_post(path, "/charts/historical", _payload(sec_id, cur, stop))
            f = _frame(body)
            if f is not None:
                frames.append(f)
        except DhanAPIError as exc:
            if "DH-907" not in str(exc):        # DH-907 = no data in window (pre-listing) — expected
                print(f"    {sym} {cur}..{stop}: {str(exc)[:80]}")
        cur = stop
    if not frames:
        return None
    df = pd.concat(frames).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def build_parquet(sym, df):
    d = OUT / f"symbol={sym}"
    d.mkdir(parents=True, exist_ok=True)
    df.assign(symbol=sym).to_parquet(d / "part.parquet", index=False)


def adjustment_flag(df):
    """Count single-day jumps >40% — a fingerprint of an UNADJUSTED split/bonus series."""
    r = df["close"].pct_change().abs()
    return int((r > 0.40).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma-separated override of the universe")
    ap.add_argument("--limit", type=int, help="only first N symbols (for validation)")
    ap.add_argument("--parquet-only", action="store_true", help="rebuild parquet from cache")
    args = ap.parse_args()

    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols else UNIVERSE)
    if args.limit:
        syms = syms[:args.limit]

    print("Loading scrip master ...")
    eq, idx = load_scrip_master()
    client = DhanClient()

    coverage, unresolved, flagged = [], [], []
    for i, sym in enumerate(syms, 1):
        r = resolve(sym, eq, idx)
        if not r or r[1] != "NSE_EQ":
            unresolved.append(sym)
            print(f"[{i}/{len(syms)}] {sym:<12} unresolved")
            continue
        sec_id = r[0]
        try:
            df = pull_symbol(client, sym, sec_id)
        except DhanAPIError as e:
            print(f"[{i}/{len(syms)}] {sym:<12} API error: {str(e)[:70]}")
            continue
        if df is None or df.empty:
            print(f"[{i}/{len(syms)}] {sym:<12} no data")
            continue
        build_parquet(sym, df)
        jumps = adjustment_flag(df)
        if jumps:
            flagged.append((sym, jumps))
        first, last = df["ts"].iloc[0].date(), df["ts"].iloc[-1].date()
        print(f"[{i}/{len(syms)}] {sym:<12} {len(df):>5} bars  {first} → {last}"
              + (f"  ⚠{jumps} split-jumps" if jumps else ""))
        coverage.append((sym, len(df), first, last))

    print(f"\n=== summary ===")
    print(f"  symbols pulled : {len(coverage)}/{len(syms)}")
    if coverage:
        earliest = min(c[2] for c in coverage)
        print(f"  earliest bar   : {earliest}   (window start {EQUITIES_START})")
        print(f"  total bars     : {sum(c[1] for c in coverage):,}")
    if unresolved:
        print(f"  unresolved     : {', '.join(unresolved)}")
    if flagged:
        print(f"  ⚠ UNADJUSTED-series suspects ({len(flagged)}): "
              f"{', '.join(f'{s}({n})' for s, n in flagged)}")
        print("    (single-day >40% jumps = likely raw split/bonus gaps — adjust before backtesting)")
    print(f"\n  parquet: {OUT}/symbol=*/part.parquet")


if __name__ == "__main__":
    main()
