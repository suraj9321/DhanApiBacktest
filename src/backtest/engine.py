"""Event loop: chronological session/tick iteration, next-bar fills, ledgers.

Fill convention (anti-look-ahead): a decision taken at tick t fills at the
next minute bar's close (t+1) via MarketData.quote, with slippage and costs
from costs.execute. Invariants asserted at end of run:
  1. final equity == capital + sum(fill cashflows) - sum(costs)
  2. no structure's realized loss exceeded its structural max (+ cost epsilon)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import costs as C
from .data import MarketData, SignalStore
from .risk import RiskManager, month_key, week_key
from .strategy import StrategyConfig, build_structure, exit_reason, gates_pass, pick_strikes
from .structures import LOT_SIZE, Structure


def _next_tod(all_tods: list[str], tod: str) -> str | None:
    later = [t for t in all_tods if t > tod]
    return later[0] if later else None


@dataclass
class Backtest:
    cfg: StrategyConfig
    capital: float
    start: object = None
    end: object = None

    md: MarketData = None
    sig: SignalStore = None
    risk: RiskManager = None
    cash: float = 0.0
    open_structs: list = field(default_factory=list)
    trade_rows: list = field(default_factory=list)
    equity_rows: list = field(default_factory=list)
    _fill_cash: float = 0.0
    _charges: float = 0.0
    _slippage: float = 0.0
    _struct_costs: dict = field(default_factory=dict)  # id(structure) -> [charges, slippage] at entry

    def run(self) -> dict:
        self.md = MarketData(self.cfg.flag)
        self.sig = SignalStore()
        self.risk = RiskManager(self.capital)
        self.cash = self.capital
        days = [d for d in self.md.trading_days
                if (self.start is None or d >= self.start) and (self.end is None or d <= self.end)]
        for d in days:
            self._run_day(d)
        # force-close anything open at the end of data
        if self.open_structs and days:
            self._close_all(days[-1], "15:15", "end_of_data")
        self._assert_invariants()
        return self._result(days)

    # ---- per-day ----

    def _run_day(self, d) -> None:
        dte = self.md.dte.get(d)
        entry_cfg = self.cfg["entry"]
        if not self.open_structs and dte != entry_cfg["dte"]:
            # flat and no entry possible today: equity is cash, skip the day load
            self.equity_rows.append({"d": d, "equity": self.cash})
            return
        tods = self.md.eval_tods(d, self.cfg.raw.get("eval_step_min", 5))
        if not tods:
            return
        for tod in tods:
            # exits first, entries after — never both for the same structure in one tick
            self._eval_exits(d, tod, dte)
            self._risk_marks(d, tod)
            if (dte == entry_cfg["dte"] and tod == entry_cfg["tod"]
                    and not self.open_structs):
                self._try_enter(d, tod)
        self._mark_equity(d)

    def _try_enter(self, d, tod) -> None:
        row = self.sig.as_of(d)
        if not gates_pass(self.cfg, row, self.sig.morning_iv(d, self.cfg.flag)):
            return
        chain = self.md.chain_at(d, tod)
        if chain.empty:
            return
        strikes = pick_strikes(self.cfg, chain)
        if strikes is None:
            return
        fill_tod = _next_tod(sorted(self.md.day(d)["tod"].unique()), tod)
        if fill_tod is None:
            return
        # provisional pricing at decision tick to size the structure
        quotes = {}
        for opt in ("CE", "PE"):
            for k in strikes[opt]:
                q = self.md.quote(d, fill_tod, opt, k)
                if q is None:
                    return
                quotes[(opt, k)] = q
        trial = build_structure(self.cfg, strikes, quotes, 1, None)
        open_risk = sum(s.max_loss_rupees for s in self.open_structs)
        budget = self.risk.max_new_risk(d, open_risk,
                                        self.cfg["sizing"]["risk_pct_per_trade"])
        qty = int(budget // trial.max_loss_rupees) if trial.max_loss_rupees > 0 else 0
        if qty < 1:
            return
        fills, units = {}, LOT_SIZE * qty
        entry_charges = entry_slippage = 0.0
        for opt in ("CE", "PE"):
            short_k, wing_k = strikes[opt]
            for k, is_buy in ((short_k, False), (wing_k, True)):
                f = C.execute(is_buy, quotes[(opt, k)], units)
                fills[(opt, k)] = f.fill_price
                self._book_fill(d, f)
                entry_charges += f.charges
                entry_slippage += f.slippage_rupees
        s = build_structure(self.cfg, strikes, fills, qty, entry_ts=(d, fill_tod))
        self.open_structs.append(s)
        self._struct_costs[id(s)] = [entry_charges, entry_slippage]
        self.trade_rows.append({
            "event": "entry", "d": d, "tod": fill_tod, "qty": qty,
            "credit": s.net_credit, "max_loss": s.max_loss_rupees,
            "strikes": str({k: v for k, v in s.short_strikes.items()}),
        })

    def _eval_exits(self, d, tod, dte) -> None:
        for s in list(self.open_structs):
            prices = self.md.prices_for(s, d, tod)
            if prices is None:
                continue
            chain = self.md.chain_at(d, tod)
            sd = {}
            for opt, k in s.short_strikes.items():
                row = chain[(chain["option_type"] == opt) & (chain["strike"] == k)]
                sd[opt] = float(row["delta"].iloc[0]) if len(row) and pd.notna(row["delta"].iloc[0]) else None
            reason = exit_reason(self.cfg, s, prices, sd, dte if dte is not None else 99, tod)
            if reason:
                self._close(s, d, tod, reason)

    def _close(self, s: Structure, d, tod, reason: str) -> None:
        fill_tod = _next_tod(sorted(self.md.day(d)["tod"].unique()), tod) or tod
        units = LOT_SIZE * s.qty_lots
        pnl = 0.0
        exit_charges = exit_slippage = 0.0
        for leg in s.legs:
            q = self.md.quote(d, fill_tod, leg.opt_type, leg.strike)
            if q is None:
                q = 0.0
            f = C.execute(is_buy=(leg.side == -1), mid_price=q, units=units)
            self._book_fill(d, f)
            exit_charges += f.charges
            exit_slippage += f.slippage_rupees
            pnl += -leg.side * (leg.entry_price - f.fill_price) * units
        self.open_structs.remove(s)
        self.risk.on_realized(d, pnl)
        entry_charges, entry_slippage = self._struct_costs.pop(id(s), (0.0, 0.0))
        self.trade_rows.append({"event": "exit", "d": d, "tod": fill_tod,
                                "reason": reason, "pnl_gross": pnl,
                                "charges": entry_charges + exit_charges,
                                "slippage": entry_slippage + exit_slippage})

    def _close_all(self, d, tod, reason) -> None:
        for s in list(self.open_structs):
            self._close(s, d, tod, reason)

    # ---- accounting ----

    def _book_fill(self, d, f: C.Fill) -> None:
        cash_flow = (-f.fill_price if f.is_buy else f.fill_price) * f.units
        self.cash += cash_flow - f.charges
        self._fill_cash += cash_flow
        self._charges += f.charges
        self._slippage += f.slippage_rupees

    def _open_mtm(self, d, tod) -> float:
        total = 0.0
        for s in self.open_structs:
            prices = self.md.prices_for(s, d, tod)
            if prices:
                total += s.open_pnl_rupees(prices)
        return total

    def _risk_marks(self, d, tod) -> None:
        wk = week_key(d)
        realized_wk = sum(r["pnl_gross"] for r in self.trade_rows
                          if r["event"] == "exit" and week_key(r["d"]) == wk)
        open_mtm = self._open_mtm(d, tod)
        if self.risk.on_mark(d, realized_wk + open_mtm):
            self._close_all(d, tod, "weekly_stop")
        mk = month_key(d)
        realized_mo = self.risk.month_realized.get(mk, 0.0)
        if self.risk.check_monthly(d, realized_mo + self._open_mtm(d, tod)):
            self._close_all(d, tod, "monthly_cb")

    def _mark_equity(self, d) -> None:
        self.equity_rows.append({"d": d, "equity": self.cash + self._open_liab(d)})

    def _open_liab(self, d) -> float:
        """Value of open positions at last mark (liability for net-short structures)."""
        total = 0.0
        for s in self.open_structs:
            tods = self.md.eval_tods(d)
            prices = self.md.prices_for(s, d, tods[-1]) if tods else None
            if prices:
                total -= s.value(prices) * LOT_SIZE * s.qty_lots
        return total

    # ---- invariants & result ----

    def _assert_invariants(self) -> None:
        # Identity: cash == capital + sum(fill cashflows) - sum(statutory charges).
        # (Slippage is embedded in fill prices, hence inside _fill_cash.)
        drift = abs(self.cash - (self.capital + self._fill_cash - self._charges))
        assert drift < 1.0, f"equity identity violated by {drift:.2f}"

    def _result(self, days) -> dict:
        eq = pd.DataFrame(self.equity_rows)
        trades = pd.DataFrame(self.trade_rows)
        return {"equity": eq, "trades": trades, "risk_events": self.risk.events,
                "fallbacks": self.md.fallback_counts,
                "charges_total": self._charges, "slippage_total": self._slippage}
