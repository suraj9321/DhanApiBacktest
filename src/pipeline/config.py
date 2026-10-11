"""Central configuration for the data pipeline.

Everything tunable lives here; no other module hardcodes paths, IDs, or limits.
Secrets come from .env (see .env.example) and are never stored in code.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# --- API ---
API_BASE = "https://api.dhan.co/v2"
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")

# Data APIs allow 5 req/s and 100k/day; we stay under both with margin.
RATE_LIMIT_RPS = 3.0
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 5

# --- Instruments (IDX_I security IDs; VIX_ID is verified by `pull_all.py --probe`) ---
NIFTY_ID = "13"
INDIA_VIX_ID = "21"

# --- Pull windows ---
# Rolling options API serves ~5 years back, max 45 days per call.
OPTIONS_START = date.today() - timedelta(days=5 * 365)
OPTIONS_WINDOW_DAYS = 45
# Intraday index data also serves ~5 years back; chunk conservatively.
INTRADAY_START = date.today() - timedelta(days=5 * 365)
INTRADAY_WINDOW_DAYS = 75
# Daily index data goes back to inception; start well before Nifty's 1996 launch.
DAILY_START = date(1995, 1, 1)

# --- Options request grid ---
EXPIRY_FLAGS = ["WEEK", "MONTH"]
# "ATM", "ATM+1" .. "ATM+10", "ATM-1" .. "ATM-10" — strike *counts* relative to
# ATM per the docs ("upto 10 strikes above and below"); semantics confirmed by probe.
STRIKE_OFFSETS = (
    ["ATM"]
    + [f"ATM+{i}" for i in range(1, 11)]
    + [f"ATM-{i}" for i in range(1, 11)]
)
OPTION_TYPES = ["CALL", "PUT"]
OPTIONS_INTERVAL = "1"  # 1-minute bars: maximum resolution, downsample later
REQUIRED_DATA = ["open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"]

# --- Storage layout ---
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # cached raw JSON, one file per API call
PARQUET_DIR = DATA_DIR / "parquet"  # normalized columnar data
META_DB = DATA_DIR / "meta.duckdb"  # mutable bookkeeping (progress, validation)

for _d in (RAW_DIR, PARQUET_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def assert_token() -> None:
    if not ACCESS_TOKEN:
        raise SystemExit(
            "DHAN_ACCESS_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

# --- Validation ---
# Min next-day/expiry-day straddle-TV jump ratio to accept a detected expiry;
# normal rolls score 20-60, the worst genuine expiry ~3; rejects data-edge periods.
EXPIRY_JUMP_MIN = 2.0
