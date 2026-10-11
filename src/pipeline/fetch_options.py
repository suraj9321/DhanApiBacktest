"""Pull 5 years of rolling (expired) options data from /charts/rollingoption.

Grid: expiry flag (WEEK/MONTH) x strike offset (ATM, ATM±1..±10) x option type,
in 45-day windows. Each call's raw JSON is cached under data/raw/rollingoption/.

Two empirical unknowns are resolved at runtime rather than assumed:
1. Whether a single call returns BOTH ce and pe arrays (the docs' response
   schema suggests it does, but the request takes drvOptionType). If both come
   back populated, PUT calls are skipped — halving the pull.
2. Strike-offset semantics ("ATM+1" = one strike step above spot). The probe
   prints strike vs spot so this can be eyeballed before the full pull.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Iterator

from . import config
from .dhan_client import DhanClient


def _windows(start: date, end: date, span_days: int) -> Iterator[tuple[date, date]]:
    cur = start
    while cur < end:
        stop = min(cur + timedelta(days=span_days - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def _payload(flag: str, offset: str, opt_type: str, frm: date, to: date) -> dict:
    return {
        "exchangeSegment": "NSE_FNO",
        "interval": config.OPTIONS_INTERVAL,
        "securityId": config.NIFTY_ID,
        "instrument": "OPTIDX",
        "expiryFlag": flag,
        "expiryCode": 1,  # near expiry — the rolling front contract
        "strike": offset,
        "drvOptionType": opt_type,
        "requiredData": config.REQUIRED_DATA,
        "fromDate": frm.isoformat(),
        "toDate": to.isoformat(),
    }


def _cache_path(flag: str, offset: str, opt_type: str, frm: date, to: date):
    return (
        config.RAW_DIR
        / "rollingoption"
        / flag.lower()
        / opt_type.lower()
        / offset.replace("+", "p").replace("-", "m").lower()
        / f"{frm.isoformat()}_{to.isoformat()}.json"
    )


def _leg_rows(body: dict, leg: str) -> int:
    data = body.get("data") or {}
    arrs = data.get(leg) or {}
    ts = arrs.get("timestamp") or []
    return len(ts)


def probe(client: DhanClient) -> bool:
    """One small call; print structure so request-grid assumptions can be verified.

    Returns True if a single CALL request also carries populated pe data.
    """
    frm = date.today() - timedelta(days=30)
    to = date.today() - timedelta(days=1)
    body = client.post("/charts/rollingoption", _payload("WEEK", "ATM", "CALL", frm, to))
    data = body.get("data") or {}
    print("rollingoption probe:")
    print(f"  top-level keys: {sorted(body.keys())}")
    print(f"  data keys: {sorted(data.keys())}")
    for leg in ("ce", "pe"):
        arrs = data.get(leg) or {}
        n = len(arrs.get("timestamp") or [])
        print(f"  {leg}: fields={sorted(arrs.keys())} bars={n}")
        if n:
            print(
                f"    first bar: ts={arrs['timestamp'][0]} "
                f"strike={arrs.get('strike', ['?'])[0]} spot={arrs.get('spot', ['?'])[0]} "
                f"close={arrs.get('close', ['?'])[0]} iv={arrs.get('iv', ['?'])[0]}"
            )
    both = _leg_rows(body, "ce") > 0 and _leg_rows(body, "pe") > 0
    print(f"  -> single call returns both legs: {both}")
    return both


def pull(client: DhanClient, skip_put_if_both_legs: bool | None = None) -> None:
    """Full grid pull. Resumable: cached windows are skipped."""
    if skip_put_if_both_legs is None:
        skip_put_if_both_legs = probe(client)

    opt_types = ["CALL"] if skip_put_if_both_legs else config.OPTION_TYPES
    end = date.today() - timedelta(days=1)
    windows = list(_windows(config.OPTIONS_START, end, config.OPTIONS_WINDOW_DAYS))
    total = len(config.EXPIRY_FLAGS) * len(config.STRIKE_OFFSETS) * len(opt_types) * len(windows)
    done = fetched = empty = 0

    for flag in config.EXPIRY_FLAGS:
        for offset in config.STRIKE_OFFSETS:
            for opt_type in opt_types:
                for frm, to in windows:
                    path = _cache_path(flag, offset, opt_type, frm, to)
                    body, was_cached = client.cached_post(
                        path, "/charts/rollingoption",
                        _payload(flag, offset, opt_type, frm, to),
                    )
                    done += 1
                    if not was_cached:
                        fetched += 1
                    if _leg_rows(body, "ce") == 0 and _leg_rows(body, "pe") == 0:
                        empty += 1
                    if done % 100 == 0:
                        print(
                            f"  options: {done}/{total} windows "
                            f"({fetched} fetched this run, {empty} empty)"
                        )
    print(f"options pull complete: {done} windows, {fetched} new, {empty} empty")
