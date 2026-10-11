"""Pull Nifty index (and India VIX) history: daily since inception, intraday 5y.

Daily uses /charts/historical (data back to instrument inception).
Intraday uses /charts/intraday in INTRADAY_WINDOW_DAYS chunks.
Raw JSON cached under data/raw/spot_daily/ and data/raw/spot_intraday/.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import config
from .dhan_client import DhanAPIError, DhanClient

_INSTRUMENTS = {
    "nifty": config.NIFTY_ID,
    "indiavix": config.INDIA_VIX_ID,
}


def _daily_payload(security_id: str, frm: date, to: date) -> dict:
    return {
        "securityId": security_id,
        "exchangeSegment": "IDX_I",
        "instrument": "INDEX",
        "fromDate": frm.isoformat(),
        "toDate": to.isoformat(),  # docs: non-inclusive
    }


def _intraday_payload(security_id: str, frm: date, to: date) -> dict:
    return {
        "securityId": security_id,
        "exchangeSegment": "IDX_I",
        "instrument": "INDEX",
        "interval": "1",
        "fromDate": frm.isoformat(),
        "toDate": to.isoformat(),
    }


def _n_bars(body: dict) -> int:
    return len(body.get("timestamp") or body.get("data", {}).get("timestamp") or [])


def pull_daily(client: DhanClient, name: str) -> None:
    """Daily OHLC from inception. Chunked by ~4y to keep responses modest."""
    sec_id = _INSTRUMENTS[name]
    end = date.today()
    cur = config.DAILY_START
    total_bars = 0
    while cur < end:
        stop = min(cur + timedelta(days=4 * 365), end)
        path = config.RAW_DIR / "spot_daily" / name / f"{cur.isoformat()}_{stop.isoformat()}.json"
        try:
            body, _ = client.cached_post(path, "/charts/historical", _daily_payload(sec_id, cur, stop))
            total_bars += _n_bars(body)
        except DhanAPIError as exc:
            # Pre-inception windows may error rather than return empty; skip them.
            print(f"  {name} daily {cur}..{stop}: {exc}")
        cur = stop
    print(f"{name} daily pull complete ({total_bars} bars)")


def pull_intraday(client: DhanClient, name: str) -> None:
    sec_id = _INSTRUMENTS[name]
    end = date.today()
    cur = config.INTRADAY_START
    total_bars = 0
    while cur < end:
        stop = min(cur + timedelta(days=config.INTRADAY_WINDOW_DAYS), end)
        path = config.RAW_DIR / "spot_intraday" / name / f"{cur.isoformat()}_{stop.isoformat()}.json"
        try:
            body, _ = client.cached_post(path, "/charts/intraday", _intraday_payload(sec_id, cur, stop))
            total_bars += _n_bars(body)
        except DhanAPIError as exc:
            print(f"  {name} intraday {cur}..{stop}: {exc}")
        cur = stop + timedelta(days=1)
    print(f"{name} intraday pull complete ({total_bars} bars)")


def probe(client: DhanClient) -> None:
    """Verify security IDs and response shape with two tiny calls."""
    for name, sec_id in _INSTRUMENTS.items():
        frm = date.today() - timedelta(days=10)
        try:
            body = client.post("/charts/historical", _daily_payload(sec_id, frm, date.today()))
            keys = sorted(body.keys())
            print(f"spot probe {name} (id={sec_id}): keys={keys} bars={_n_bars(body)}")
        except DhanAPIError as exc:
            print(f"spot probe {name} (id={sec_id}) FAILED: {exc}")
