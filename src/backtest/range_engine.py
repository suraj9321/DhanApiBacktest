"""Range-breakout strangle engine (naked, stop-loss only — no structural hedge).

Independent-leg strategy, distinct in shape from the condor/fly engine: CE and
PE positions are entered/exited independently, and a breach can trigger a
same-week directional flip. Reuses MarketData, RiskManager, costs.execute;
does NOT use the Structure class (naked legs are unrepresentable there by
design — see structures.py).

Mechanics (see configs/range_strangle_v01.yaml for the tunable knobs; see
notes/backtests/run-2026-07-2x-range-strangle.md for the interpretation
choices this file encodes):
  1. Entry tick: classify loc = (spot - prev_week_low) / (prev_week_high -
     prev_week_low) against near_low_max / near_high_min. Sell CE only, PE
     only, or both.
  2. Strike = nearest listed strike to boundary * (1 +/- dist_pct).
  3. Sizing: no structural max loss (naked), so risk is proxied as
     gap_multiple * |strike - boundary| per unit, fed to the same
     RiskManager budget used elsewhere.
  4. Breach stop: spot crosses the boundary against an open leg -> exit next
     bar, then (once per week) open the opposite side at spot*(1-+dist_pct)
     with no further breach-stop (direction "confirmed").
  5. Backstop exits per leg: profit_target_pct of that leg's own credit, or
     hard time (dte, tod).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import duckdb
import pandas as pd

from . import costs as C
from .data import MarketData
from .risk import RiskManager, month_key, week_key
from .structures import LOT_SIZE

SPOT_DAILY = "read_parquet('data/parquet/spot/nifty_daily/*/*.parquet', hive_partitioning=true)"


def week_keys_sequence(dates: list) -> dict:
    """d -> (this week's key, previous week's key), built off real calendar
    weeks so 'previous' is exact even across year boundaries."""
    wks = sorted(set(week_key(d) for d in dates))
    prev = {wks[i]: wks[i - 1] for i in range(1, len(wks))}
    return prev


@dataclass
class Leg:
    opt_type: str
    strike: float
    entry_price: float
    qty_lots: int
    entry_ts: tuple
    boundary: float | None  # None once flipped (no further breach-stop)
    max_loss_per_unit: float  # naked: (premium_stop_multiple-1)*credit proxy; hedged: exact (wing_width - net_credit)
    hedge_strike: float | None = None
    hedge_entry_price: float | None = None  # premium paid for the long wing, per unit


@dataclass
class RangeStrangleConfig:
    raw: dict

    @classmethod
    def load(cls, path):
        import yaml
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def name(self):
        return self.raw["name"]


@dataclass
class RangeStrangleBacktest:
    cfg: RangeStrangleConfig
    capital: float
    start: object = None
    end: object = None

    md: MarketData = None
    risk: RiskManager = None
    cash: float = 0.0
    legs: dict = field(default_factory=dict)   # {"CE": Leg|None, "PE": Leg|None}
    flipped_this_week: set = field(default_factory=set)
    trade_rows: list = field(default_factory=list)
    equity_rows: list = field(default_factory=list)
    _fill_cash: float = 0.0
    _charges: float = 0.0
    _slippage: float = 0.0

    def run(self) -> dict:
        self.md = MarketData("week")
        self.risk = RiskManager(self.capital)
        self.cash = self.capital
        self.legs = {"CE": None, "PE": None}
        days = [d for d in self.md.trading_days
                if (self.start is None or d >= self.start) and (self.end is None or d <= self.end)]
        prev_wk_of = week_keys_sequence(self.md.trading_days)
        ranges = self._week_ranges()
        for d in days:
            self._run_day(d, prev_wk_of, ranges)
        if any(self.legs.values()) and days:
            self._close_all(days[-1], "15:15", "end_of_data")
        self._assert_invariants()
        return self._result()

    def _week_ranges(self) -> dict:
        con = duckdb.connect()
        df = con.execute(f"""
            SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, high, low
            FROM {SPOT_DAILY} ORDER BY d
        """).fetchdf()
        df["d"] = pd.to_datetime(df["d"]).dt.date
        df["wk"] = df["d"].apply(week_key)
        g = df.groupby("wk").agg(high=("high", "max"), low=("low", "min"))
        return g.to_dict("index")

    def _run_day(self, d, prev_wk_of, ranges) -> None:
        dte = self.md.dte.get(d)
        entry_cfg = self.cfg["entry"]
        wk = week_key(d)
        tods = self.md.eval_tods(d, self.cfg.raw.get("eval_step_min", 5))
        if not tods:
            self.equity_rows.append({"d": d, "equity": self.cash})
            return
        for tod in tods:
            self._eval_exits(d, tod, dte)
            self._risk_marks(d, tod)
            if (dte == entry_cfg["dte"] and tod == entry_cfg["tod"]
                    and not any(self.legs.values())):
                self._try_enter(d, tod, wk, prev_wk_of, ranges)
        self._mark_equity(d, tods[-1])

    # ---- entry ----

    def _try_enter(self, d, tod, wk, prev_wk_of, ranges) -> None:
        if self.risk.entries_blocked(d):
            return
        prev_wk = prev_wk_of.get(wk)
        rng = ranges.get(prev_wk)
        if rng is None:
            return
        high, low = rng["high"], rng["low"]
        if high <= low:
            return
        chain = self.md.chain_at(d, tod)
        if chain.empty:
            return
        spot = float(chain["spot"].median())
        loc = max(0.0, min(1.0, (spot - low) / (high - low)))
        s = self.cfg["strikes"]
        in_range = s["near_low_max"] < loc < s["near_high_min"]
        # near LOW (loc small) -> sell calls only; near HIGH (loc large) -> sell puts only
        sell_ce = loc <= s["near_low_max"] or in_range
        sell_pe = loc >= s["near_high_min"] or in_range
        dist = s["dist_pct"] / 100.0
        fill_tod = _next_tod(sorted(self.md.day(d)["tod"].unique()), tod)
        if fill_tod is None:
            return
        if sell_ce:
            self._open_leg(d, fill_tod, "CE", high * (1 + dist), chain, boundary=high, spot=spot)
        if sell_pe:
            self._open_leg(d, fill_tod, "PE", low * (1 - dist), chain, boundary=low, spot=spot)

    def _open_leg(self, d, fill_tod, opt_type, want_strike, chain, boundary, spot) -> None:
        side = chain[(chain["option_type"] == opt_type) & chain["delta"].notna()]
        if side.empty:
            return
        avail = side["strike"].values
        strike = float(avail[abs(avail - want_strike).argmin()])
        if boundary is not None:
            # Guard: our data only covers ATM +/-10 strike offsets, so the
            # true 1.5%-out strike may not be listed and the nearest-available
            # fallback can land right ON the boundary, collapsing the sizing
            # denominator. Require the picked strike to be outside the
            # boundary by at least half the intended cushion, else skip —
            # a degenerate near-ATM "OTM" strike isn't the strategy.
            min_dist = 0.5 * self.cfg["strikes"]["dist_pct"] / 100.0 * boundary
            outside = strike > boundary if opt_type == "CE" else strike < boundary
            if not outside or abs(strike - boundary) < min_dist:
                return
        q = self.md.quote(d, fill_tod, opt_type, strike)
        if q is None or q <= 0:
            return

        hedge_cfg = self.cfg.raw.get("hedge")
        hedge_strike = hedge_q = None
        if hedge_cfg:
            want_hedge = strike + hedge_cfg["width_pts"] if opt_type == "CE" else strike - hedge_cfg["width_pts"]
            beyond = avail[avail > strike] if opt_type == "CE" else avail[avail < strike]
            if len(beyond) == 0:
                return  # no strike further out to hedge with -- skip rather than trade naked
            hedge_strike = float(beyond[abs(beyond - want_hedge).argmin()])
            hedge_q = self.md.quote(d, fill_tod, opt_type, hedge_strike)
            if hedge_q is None:
                return

        if hedge_cfg:
            # Defined-risk spread: max loss is exact (wing width - net credit),
            # same pattern as the condor engine -- no premium-multiple proxy
            # and no separate margin guess needed, since a hedged spread's
            # margin requirement is itself ~ the max loss.
            net_credit = q - hedge_q
            if net_credit <= 0:
                return
            risk_per_unit = abs(hedge_strike - strike) - net_credit
            if risk_per_unit <= 0:
                return  # wing too tight to lose money on -- degenerate, skip
            qty = int(self.risk.max_new_risk(d, self._open_risk_rupees(),
                      self.cfg["sizing"]["risk_pct_per_trade"]) // (risk_per_unit * LOT_SIZE))
        else:
            # Naked path (see run-2026-07-20-range-strangle.md): size against
            # the premium-multiple stop, capped by a rough margin proxy since
            # nothing structurally bounds the loss.
            stop_mult = self.cfg["exits"].get("premium_stop_multiple")
            risk_per_unit = (stop_mult - 1) * q if stop_mult else q
            if risk_per_unit <= 0:
                return
            open_risk = self._open_risk_rupees()
            budget = self.risk.max_new_risk(d, open_risk, self.cfg["sizing"]["risk_pct_per_trade"])
            qty_risk = int(budget // (risk_per_unit * LOT_SIZE))
            margin_pct = self.cfg["sizing"].get("margin_pct_of_notional")
            if margin_pct is not None:
                margin_per_unit = margin_pct / 100.0 * spot
                margin_used = self._open_margin_rupees(spot)
                margin_left = max(self.capital - margin_used, 0.0)
                qty_margin = int(margin_left // (margin_per_unit * LOT_SIZE))
                qty = min(qty_risk, qty_margin)
            else:
                qty = qty_risk
        if qty < 1:
            return
        units = LOT_SIZE * qty
        f = C.execute(is_buy=False, mid_price=q, units=units)
        self._book_fill(f)
        fh = None
        if hedge_cfg:
            fh = C.execute(is_buy=True, mid_price=hedge_q, units=units)
            self._book_fill(fh)
            max_loss_pu = abs(hedge_strike - strike) - (f.fill_price - fh.fill_price)
        else:
            stop_mult = self.cfg["exits"].get("premium_stop_multiple")
            max_loss_pu = (stop_mult - 1) * f.fill_price if stop_mult else f.fill_price
        self.legs[opt_type] = Leg(opt_type, strike, f.fill_price, qty, (d, fill_tod), boundary, max_loss_pu,
                                  hedge_strike=hedge_strike,
                                  hedge_entry_price=(fh.fill_price if fh else None))
        self.trade_rows.append({"event": "entry", "d": d, "tod": fill_tod, "opt_type": opt_type,
                                "strike": strike, "qty": qty, "credit": f.fill_price,
                                "hedge_strike": hedge_strike, "boundary": boundary})

    def _open_risk_rupees(self) -> float:
        return sum(leg.max_loss_per_unit * LOT_SIZE * leg.qty_lots
                   for leg in self.legs.values() if leg)

    def _open_margin_rupees(self, spot: float) -> float:
        margin_pct = self.cfg["sizing"].get("margin_pct_of_notional")
        if margin_pct is None:
            return 0.0
        per_unit = margin_pct / 100.0 * spot
        return sum(per_unit * LOT_SIZE * leg.qty_lots for leg in self.legs.values() if leg)

    # ---- exits ----

    def _eval_exits(self, d, tod, dte) -> None:
        chain = None
        for opt_type in ("CE", "PE"):
            leg = self.legs[opt_type]
            if leg is None:
                continue
            q = self.md.quote(d, tod, opt_type, leg.strike)
            if q is None:
                continue
            e = self.cfg["exits"]
            hard = e.get("hard") or {}
            reason = None
            if dte is not None and (dte < hard.get("dte", 0)
                                     or (dte == hard.get("dte", 0) and tod >= hard.get("tod", "15:15"))):
                reason = "hard_time"
            elif leg.boundary is not None:
                if chain is None:
                    chain = self.md.chain_at(d, tod)
                spot = float(chain["spot"].median()) if not chain.empty else None
                breached = (spot is not None and
                            ((opt_type == "CE" and spot > leg.boundary) or
                             (opt_type == "PE" and spot < leg.boundary)))
                if breached:
                    reason = "breach_stop"
            if reason is None:
                mult = e.get("premium_stop_multiple")
                if mult is not None and q >= mult * leg.entry_price:
                    reason = "premium_stop"
            if reason is None:
                decay_pct = e.get("profit_decay_target_pct")
                if decay_pct is not None and q <= (1 - decay_pct / 100.0) * leg.entry_price:
                    reason = "target"
            if reason:
                self._close_leg(opt_type, d, tod, reason, chain)

    def _close_leg(self, opt_type, d, tod, reason, chain) -> None:
        leg = self.legs[opt_type]
        fill_tod = _next_tod(sorted(self.md.day(d)["tod"].unique()), tod) or tod
        units = LOT_SIZE * leg.qty_lots
        q = self.md.quote(d, fill_tod, opt_type, leg.strike)
        if q is None:
            q = 0.0
        f = C.execute(is_buy=True, mid_price=q, units=units)
        self._book_fill(f)
        pnl = (leg.entry_price - f.fill_price) * units
        if leg.hedge_strike is not None:
            hq = self.md.quote(d, fill_tod, opt_type, leg.hedge_strike)
            if hq is None:
                hq = 0.0
            fh = C.execute(is_buy=False, mid_price=hq, units=units)
            self._book_fill(fh)
            pnl += (fh.fill_price - leg.hedge_entry_price) * units
        self.legs[opt_type] = None
        self.risk.on_realized(d, pnl)
        self.trade_rows.append({"event": "exit", "d": d, "tod": fill_tod, "opt_type": opt_type,
                                "reason": reason, "pnl_gross": pnl})
        wk = week_key(d)
        if reason == "breach_stop" and wk not in self.flipped_this_week:
            self.flipped_this_week.add(wk)
            other = "PE" if opt_type == "CE" else "CE"
            if self.legs[other] is None:
                self._flip(other, d, fill_tod)

    def _flip(self, opt_type, d, fill_tod) -> None:
        s = self.cfg["strikes"]
        dist = s["dist_pct"] / 100.0
        chain = self.md.chain_at(d, fill_tod)
        if chain.empty:
            return
        spot = float(chain["spot"].median())
        want = spot * (1 + dist) if opt_type == "CE" else spot * (1 - dist)
        self._open_leg(d, fill_tod, opt_type, want, chain, boundary=None, spot=spot)
        if self.legs[opt_type] is not None:
            self.trade_rows[-1]["reason_tag"] = "flip"

    def _close_all(self, d, tod, reason) -> None:
        chain = self.md.chain_at(d, tod)
        for opt_type in ("CE", "PE"):
            if self.legs[opt_type] is not None:
                self._close_leg(opt_type, d, tod, reason, chain)

    # ---- accounting ----

    def _book_fill(self, f: C.Fill) -> None:
        cash_flow = (-f.fill_price if f.is_buy else f.fill_price) * f.units
        self.cash += cash_flow - f.charges
        self._fill_cash += cash_flow
        self._charges += f.charges
        self._slippage += f.slippage_rupees

    def _risk_marks(self, d, tod) -> None:
        wk = week_key(d)
        realized_wk = sum(r["pnl_gross"] for r in self.trade_rows
                          if r["event"] == "exit" and week_key(r["d"]) == wk)
        open_mtm = self._open_mtm(d, tod)
        week_pnl = realized_wk + open_mtm
        if self.risk.on_mark(d, week_pnl):
            self._close_all(d, tod, "weekly_stop")
        target_pct = self.cfg["exits"].get("weekly_target_roi_pct")
        if (target_pct is not None and any(self.legs.values())
                and week_pnl >= target_pct / 100.0 * self.capital):
            self._close_all(d, tod, "target_roi")
        mk = month_key(d)
        realized_mo = self.risk.month_realized.get(mk, 0.0)
        if self.risk.check_monthly(d, realized_mo + open_mtm):
            self._close_all(d, tod, "monthly_cb")

    def _open_mtm(self, d, tod) -> float:
        total = 0.0
        for opt_type, leg in self.legs.items():
            if leg is None:
                continue
            q = self.md.quote(d, tod, opt_type, leg.strike)
            if q is not None:
                total += (leg.entry_price - q) * LOT_SIZE * leg.qty_lots
            if leg.hedge_strike is not None:
                hq = self.md.quote(d, tod, opt_type, leg.hedge_strike)
                if hq is not None:
                    total += (hq - leg.hedge_entry_price) * LOT_SIZE * leg.qty_lots
        return total

    def _mark_equity(self, d, last_tod) -> None:
        self.equity_rows.append({"d": d, "equity": self.cash + self._open_liab(d, last_tod)})

    def _open_liab(self, d, tod) -> float:
        total = 0.0
        for opt_type, leg in self.legs.items():
            if leg is None:
                continue
            q = self.md.quote(d, tod, opt_type, leg.strike)
            if q is not None:
                total -= q * LOT_SIZE * leg.qty_lots
            if leg.hedge_strike is not None:
                hq = self.md.quote(d, tod, opt_type, leg.hedge_strike)
                if hq is not None:
                    total += hq * LOT_SIZE * leg.qty_lots
        return total

    def _assert_invariants(self) -> None:
        drift = abs(self.cash - (self.capital + self._fill_cash - self._charges))
        assert drift < 1.0, f"equity identity violated by {drift:.2f}"

    def _result(self) -> dict:
        eq = pd.DataFrame(self.equity_rows)
        trades = pd.DataFrame(self.trade_rows)
        return {"equity": eq, "trades": trades, "risk_events": self.risk.events,
                "fallbacks": self.md.fallback_counts,
                "charges_total": self._charges, "slippage_total": self._slippage}


def _next_tod(all_tods: list[str], tod: str) -> str | None:
    later = [t for t in all_tods if t > tod]
    return later[0] if later else None
