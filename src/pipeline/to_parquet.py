"""Normalize cached raw JSON into partitioned Parquet.

Layout (see notes/data-pipeline.md for the design rationale):

  data/parquet/options/flag=week/month=2024-03/part.parquet
      columns: ts(UTC), option_type, strike_offset(int), open, high, low,
               close, iv, volume, oi, strike, spot
      sorted by (option_type, strike_offset, ts) -> row-group zone maps prune
      both strike and time predicates without any index.

  data/parquet/spot/{name}_daily/year=2024/part.parquet
  data/parquet/spot/{name}_intraday/year=2024/part.parquet

Partitioning is by calendar month, NOT by expiry: expiry assignment needs the
exact NSE holiday calendar, and a calendar mistake would misfile rows at the
storage layer. As a continuous time series, an expiry week is just a time-range
filter; a later enrichment step adds expiry_date as a *column*, where errors
are correctable updates rather than misfiled files.

Rebuilds are idempotent: each partition is fully rewritten from raw on every
run (raw JSON remains the source of truth).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import config

_OFFSET_FROM_DIR = {"atm": 0}
for _i in range(1, 11):
    _OFFSET_FROM_DIR[f"atmp{_i}"] = _i
    _OFFSET_FROM_DIR[f"atmm{_i}"] = -_i

_NUMERIC = ["open", "high", "low", "close", "iv", "volume", "oi", "strike", "spot"]


def _leg_frame(arrs: dict, option_type: str, strike_offset: int) -> pd.DataFrame | None:
    ts = arrs.get("timestamp") or []
    if not ts:
        return None
    df = pd.DataFrame({"epoch": pd.array(ts, dtype="int64")})
    for col in _NUMERIC:
        vals = arrs.get(col)
        df[col] = pd.array(vals, dtype="float64") if vals is not None else pd.NA
    df["ts"] = pd.to_datetime(df.pop("epoch"), unit="s", utc=True)
    df["option_type"] = option_type
    df["strike_offset"] = strike_offset
    return df


def build_options() -> None:
    raw_root = config.RAW_DIR / "rollingoption"
    if not raw_root.exists():
        print("no raw options data yet")
        return

    # Group frames by (flag, month) partition, then write each once.
    buckets: dict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)
    n_files = 0
    for path in sorted(raw_root.rglob("*.json")):
        flag = path.relative_to(raw_root).parts[0]  # week / month
        offset = _OFFSET_FROM_DIR[path.parent.name]
        with path.open() as f:
            body = json.load(f)
        data = body.get("data") or {}
        for leg, opt_type in (("ce", "CE"), ("pe", "PE")):
            df = _leg_frame(data.get(leg) or {}, opt_type, offset)
            if df is None:
                continue
            for month, part in df.groupby(df["ts"].dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m")):
                buckets[(flag, str(month))].append(part)
        n_files += 1

    for (flag, month), frames in sorted(buckets.items()):
        df = pd.concat(frames, ignore_index=True)
        # Windows can only overlap at edges; the raw cache may also hold a
        # CALL and a PUT request that each returned both legs -> dedupe.
        df = df.drop_duplicates(subset=["option_type", "strike_offset", "ts"])
        df = df.sort_values(["option_type", "strike_offset", "ts"])
        out = config.PARQUET_DIR / "options" / f"flag={flag}" / f"month={month}"
        out.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out / "part.parquet", index=False)
    print(f"options parquet built from {n_files} raw files -> {len(buckets)} partitions")


def _spot_frames(raw_dir: Path) -> pd.DataFrame | None:
    frames = []
    for path in sorted(raw_dir.glob("*.json")):
        with path.open() as f:
            body = json.load(f)
        arrs = body if "timestamp" in body else body.get("data", {})
        ts = arrs.get("timestamp") or []
        if not ts:
            continue
        df = pd.DataFrame({"epoch": pd.array(ts, dtype="int64")})
        for col in ("open", "high", "low", "close", "volume"):
            vals = arrs.get(col)
            df[col] = pd.array(vals, dtype="float64") if vals is not None else pd.NA
        df["ts"] = pd.to_datetime(df.pop("epoch"), unit="s", utc=True)
        frames.append(df)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates(subset=["ts"]).sort_values("ts")


def build_spot() -> None:
    for kind in ("spot_daily", "spot_intraday"):
        base = config.RAW_DIR / kind
        if not base.exists():
            continue
        for inst_dir in sorted(base.iterdir()):
            if not inst_dir.is_dir():
                continue
            df = _spot_frames(inst_dir)
            if df is None:
                continue
            name = f"{inst_dir.name}_{kind.removeprefix('spot_')}"
            for year, part in df.groupby(df["ts"].dt.tz_convert("Asia/Kolkata").dt.year):
                out = config.PARQUET_DIR / "spot" / name / f"year={year}"
                out.mkdir(parents=True, exist_ok=True)
                part.to_parquet(out / "part.parquet", index=False)
            print(f"spot parquet built: {name} ({len(df)} bars)")
