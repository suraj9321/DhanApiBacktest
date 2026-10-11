"""Single source of truth for transaction costs — every fill passes through here.

Rates as of 2026 (verify before live; see notes/risk-framework.md):
brokerage flat/order, STT on sell premium, NSE txn charge on premium turnover,
GST on (brokerage + txn), stamp duty on buy premium, SEBI fee. Slippage is
modeled as half the bid-ask spread, scaling with premium (far OTM crosses
proportionally wider spreads) and clamped to sane bounds.
"""
from __future__ import annotations

from dataclasses import dataclass

BROKERAGE_PER_ORDER = 20.0
STT_SELL = 0.001          # 0.1% of sell-side premium
EXCH_TXN = 0.0003503      # NSE options, on premium turnover
GST = 0.18                # on brokerage + exchange txn
STAMP_BUY = 0.00003       # 0.003% buy side
SEBI_FEE = 10 / 1e7       # per rupee of turnover

SLIP_FRAC = 0.002         # half-spread ≈ 0.2% of premium (calibrate vs live before real money)
SLIP_MIN = 0.05           # ... clamped to [0.05, 1.5] points
SLIP_MAX = 0.75


def slippage_points(premium: float) -> float:
    return min(max(premium * SLIP_FRAC, SLIP_MIN), SLIP_MAX)


@dataclass(frozen=True)
class Fill:
    """One executed order (one leg, one direction)."""
    is_buy: bool
    mid_price: float       # per-unit quote used for the fill
    fill_price: float      # after slippage
    units: int             # LOT_SIZE * qty_lots
    charges: float         # statutory + brokerage, rupees
    slippage_rupees: float

    @property
    def total_cost(self) -> float:
        return self.charges + self.slippage_rupees


def execute(is_buy: bool, mid_price: float, units: int) -> Fill:
    slip = slippage_points(mid_price)
    fill_price = mid_price + slip if is_buy else max(mid_price - slip, 0.05)
    turnover = fill_price * units
    charges = BROKERAGE_PER_ORDER + EXCH_TXN * turnover + SEBI_FEE * turnover
    if is_buy:
        charges += STAMP_BUY * turnover
    else:
        charges += STT_SELL * turnover
    charges += GST * (BROKERAGE_PER_ORDER + EXCH_TXN * turnover)
    return Fill(is_buy, mid_price, fill_price, units, charges,
                abs(fill_price - mid_price) * units)
