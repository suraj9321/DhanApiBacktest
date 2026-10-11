"""Defined-risk option structures. Naked shorts are unrepresentable by design:
a Structure validates at construction that every short leg is covered by a
long wing further out on the same side, and max structural loss is computed
up front — the number all risk sizing uses (see notes/risk-framework.md).

Sign convention: side +1 = long, -1 = short. Prices are per-unit points;
rupee amounts = points * LOT_SIZE * qty_lots.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LOT_SIZE = 75


@dataclass(frozen=True)
class Leg:
    opt_type: str          # "CE" | "PE"
    strike: float
    side: int              # +1 long, -1 short
    entry_price: float     # per-unit fill price

    def __post_init__(self):
        if self.opt_type not in ("CE", "PE"):
            raise ValueError(f"bad opt_type {self.opt_type}")
        if self.side not in (+1, -1):
            raise ValueError(f"bad side {self.side}")


@dataclass
class Structure:
    kind: str              # "condor" | "fly"
    legs: list[Leg]
    qty_lots: int
    entry_ts: object = None
    exit_reason: str | None = None
    field_notes: dict = field(default_factory=dict)

    def __post_init__(self):
        shorts = [l for l in self.legs if l.side == -1]
        longs = [l for l in self.legs if l.side == +1]
        if len(shorts) != 2 or len(longs) != 2:
            raise ValueError("structure must have exactly 2 short + 2 long legs")
        for s in shorts:
            covers = [l for l in longs if l.opt_type == s.opt_type]
            if not covers:
                raise ValueError(f"short {s.opt_type} leg has no wing")
            w = covers[0]
            outside = w.strike > s.strike if s.opt_type == "CE" else w.strike < s.strike
            if not outside:
                raise ValueError(f"{s.opt_type} wing not outside short strike")
        if self.qty_lots < 1:
            raise ValueError("qty_lots must be >= 1")

    # ---- per-unit economics ----

    @property
    def net_credit(self) -> float:
        """Per-unit premium received at entry (positive for a credit structure)."""
        return sum(-l.side * l.entry_price for l in self.legs)

    @property
    def put_width(self) -> float:
        s = next(l for l in self.legs if l.side == -1 and l.opt_type == "PE")
        w = next(l for l in self.legs if l.side == +1 and l.opt_type == "PE")
        return s.strike - w.strike

    @property
    def call_width(self) -> float:
        s = next(l for l in self.legs if l.side == -1 and l.opt_type == "CE")
        w = next(l for l in self.legs if l.side == +1 and l.opt_type == "CE")
        return w.strike - s.strike

    @property
    def max_loss_per_unit(self) -> float:
        """Worst-case expiry loss per unit: widest side minus the credit."""
        return max(self.put_width, self.call_width) - self.net_credit

    @property
    def max_loss_rupees(self) -> float:
        return self.max_loss_per_unit * LOT_SIZE * self.qty_lots

    @property
    def short_strikes(self) -> dict[str, float]:
        return {l.opt_type: l.strike for l in self.legs if l.side == -1}

    def value(self, prices: dict[tuple[str, float], float]) -> float:
        """Per-unit cost to close now (positive = we pay to close shorts net)."""
        return sum(-l.side * prices[(l.opt_type, l.strike)] for l in self.legs)

    def open_pnl_per_unit(self, prices: dict[tuple[str, float], float]) -> float:
        return self.net_credit - self.value(prices)

    def open_pnl_rupees(self, prices) -> float:
        return self.open_pnl_per_unit(prices) * LOT_SIZE * self.qty_lots
