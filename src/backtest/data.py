"""MarketData facade + SignalStore — the only code that touches Parquet.

Look-ahead protection is structural:
- SignalStore.as_of(d) returns the latest signal row STRICTLY BEFORE d
  (i.e., T-1 15:15 or earlier); _EVAL columns are dropped at load.
- MarketData serves quotes by exact timestamp; the engine's next-bar fill
  convention lives in engine.py.

Quotes: per-day slices from options_enriched, cached LRU. Missing far-OTM
minutes forward-fill within the day (staleness capped); a leg absent all day
falls back to intrinsic value against the forward (flagged in stats).
"""
from __future__ import annotations

from collections import OrderedDict

import duckdb
import numpy as np
import pandas as pd

OPT = "read_parquet('data/parquet/options_enriched/*/*/*.parquet', hive_partitioning=true)"
SIGNALS = "read_parquet('data/parquet/signals/daily_signals.parquet')"


class MarketData:
    def __init__(self, flag: str, cache_days: int = 8):
        self.flag = flag
        self.cache_days = cache_days
        self._cache: OrderedDict = OrderedDict()
        self._con = duckdb.connect()
        self.fallback_counts = {"ffill": 0, "intrinsic": 0}
        cal = self._con.execute(f"""
            SELECT DISTINCT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, expiry_date
            FROM {OPT} WHERE flag='{self.flag}' AND NOT special_session
              AND expiry_date IS NOT NULL ORDER BY d
        """).fetchdf()
        cal["d"] = pd.to_datetime(cal["d"]).dt.date
        cal["expiry_date"] = pd.to_datetime(cal["expiry_date"]).dt.date
        self.calendar = cal.set_index("d")["expiry_date"].to_dict()
        self.trading_days = sorted(self.calendar)
        # sessions-remaining (dte) per day within its expiry cycle
        cyc = cal.groupby("expiry_date")["d"].apply(list).to_dict()
        self.dte = {}
        for exp, days in cyc.items():
            for i, d in enumerate(sorted(days, reverse=True)):
                self.dte[d] = i

    def day(self, d) -> pd.DataFrame:
        if d in self._cache:
            self._cache.move_to_end(d)
            return self._cache[d]
        df = self._con.execute(f"""
            SELECT ts, option_type, strike, close, delta, iv, spot, fwd, tau,
                   strftime(ts AT TIME ZONE 'Asia/Kolkata', '%H:%M') AS tod
            FROM {OPT}
            WHERE flag='{self.flag}' AND NOT special_session
              AND CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) = DATE '{d}'
            ORDER BY ts
        """).fetchdf()
        self._cache[d] = df
        if len(self._cache) > self.cache_days:
            self._cache.popitem(last=False)
        return df

    def chain_at(self, d, tod: str) -> pd.DataFrame:
        df = self.day(d)
        return df[df["tod"] == tod]

    def quote(self, d, tod: str, opt_type: str, strike: float) -> float | None:
        """Close at (d, tod) for a leg; ffill within day; intrinsic fallback."""
        df = self.day(d)
        leg = df[(df["option_type"] == opt_type) & (df["strike"] == strike)]
        exact = leg[leg["tod"] == tod]
        if len(exact):
            return float(exact["close"].iloc[0])
        earlier = leg[leg["tod"] < tod]
        if len(earlier):
            self.fallback_counts["ffill"] += 1
            return float(earlier["close"].iloc[-1])
        # leg absent all day so far: intrinsic vs forward at nearest bar
        self.fallback_counts["intrinsic"] += 1
        at_tod = df[df["tod"] <= tod]
        if at_tod.empty:
            return None
        fwd = float(at_tod["fwd"].iloc[-1])
        return max(fwd - strike, 0.0) if opt_type == "CE" else max(strike - fwd, 0.0)

    def prices_for(self, structure, d, tod: str) -> dict | None:
        out = {}
        for leg in structure.legs:
            p = self.quote(d, tod, leg.opt_type, leg.strike)
            if p is None:
                return None
            out[(leg.opt_type, leg.strike)] = p
        return out

    def eval_tods(self, d, step_min: int = 5) -> list[str]:
        df = self.day(d)
        tods = sorted(df["tod"].unique())
        return [t for t in tods if int(t[3:]) % step_min == 0]


class SignalStore:
    def __init__(self):
        con = duckdb.connect()
        df = con.execute(f"SELECT * FROM {SIGNALS} ORDER BY d").fetchdf()
        df = df[[c for c in df.columns if not c.endswith("_EVAL")]]
        df["d"] = pd.to_datetime(df["d"]).dt.date
        self._df = df.set_index("d")
        self._dates = np.array(sorted(self._df.index))

    def as_of(self, d) -> pd.Series | None:
        """Latest signal row strictly before d (T-1 EOD wall)."""
        i = np.searchsorted(self._dates, d) - 1
        if i < 0:
            return None
        return self._df.loc[self._dates[i]]

    def morning_iv(self, d, flag: str) -> float | None:
        """Same-morning 09:20 IV — the only same-day field a gate may use."""
        col = f"iv_{flag}_0920"
        if d in self._df.index and col in self._df.columns:
            v = self._df.loc[d, col]
            return float(v) if np.isfinite(v) else None
        return None
