"""Four-layer risk manager (notes/risk-framework.md). The engine consults it at
every evaluation tick and before every entry; strategies cannot override it.

Layer 1 (per-structure stop) lives in strategy.exit_reason.
Layer 2: weekly hard stop  — 4% of trading capital -> flat, no re-entry this week.
Layer 3: monthly circuit-breaker — 5% -> flat, no entries until next month;
         plus forced downsizing: new entries' max loss must fit the remaining
         monthly budget.
Layer 4: structural bound — sum of open max losses (incl. proposed) <= 8%.

Weeks are Mon-Sun; months are calendar. P&L attribution: realized on exit
fills, marked-to-market for open structures at each tick.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

WEEKLY_STOP = 0.04
MONTHLY_CB = 0.05
STRUCT_BOUND = 0.08


def week_key(d: date) -> str:
    return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"


def month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


@dataclass
class RiskManager:
    capital: float
    week_pnl: dict = field(default_factory=dict)    # realized + mtm, by week key
    month_realized: dict = field(default_factory=dict)
    week_stopped: set = field(default_factory=set)
    month_stopped: set = field(default_factory=set)
    events: list = field(default_factory=list)

    # ---- accounting hooks (called by the engine) ----

    def on_realized(self, d: date, pnl: float) -> None:
        self.month_realized[month_key(d)] = self.month_realized.get(month_key(d), 0.0) + pnl

    def on_mark(self, d: date, week_realized_plus_open: float) -> bool:
        """Update weekly mark; returns True if the weekly stop just fired."""
        wk = week_key(d)
        self.week_pnl[wk] = week_realized_plus_open
        if wk not in self.week_stopped and week_realized_plus_open <= -WEEKLY_STOP * self.capital:
            self.week_stopped.add(wk)
            self.events.append((d, "weekly_stop", week_realized_plus_open))
            return True
        return False

    def check_monthly(self, d: date, month_realized_plus_open: float) -> bool:
        mk = month_key(d)
        if mk not in self.month_stopped and month_realized_plus_open <= -MONTHLY_CB * self.capital:
            self.month_stopped.add(mk)
            self.events.append((d, "monthly_cb", month_realized_plus_open))
            return True
        return False

    # ---- entry authorization ----

    def entries_blocked(self, d: date) -> bool:
        return week_key(d) in self.week_stopped or month_key(d) in self.month_stopped

    def max_new_risk(self, d: date, open_max_loss: float, risk_per_trade_pct: float) -> float:
        """Rupee budget for a new structure's max loss (0 = no entry).

        min(per-trade budget, remaining monthly budget [forced downsizing],
        remaining structural headroom).
        """
        if self.entries_blocked(d):
            return 0.0
        per_trade = risk_per_trade_pct / 100.0 * self.capital
        month_used = -min(self.month_realized.get(month_key(d), 0.0), 0.0)
        month_left = max(MONTHLY_CB * self.capital - month_used, 0.0)
        struct_left = max(STRUCT_BOUND * self.capital - open_max_loss, 0.0)
        return max(min(per_trade, month_left, struct_left), 0.0)
