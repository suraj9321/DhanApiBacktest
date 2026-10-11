"""Rupee-exact unit tests for structures and costs — the money math must be
provably right before any backtest result is believed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from backtest import costs as C
from backtest.structures import LOT_SIZE, Leg, Structure


def condor():
    # Sell 24300CE@52.55, buy 24700CE@8.0; sell 24100PE@61.9, buy 23800PE@12.0
    return Structure("condor", [
        Leg("CE", 24300, -1, 52.55), Leg("CE", 24700, +1, 8.00),
        Leg("PE", 24100, -1, 61.90), Leg("PE", 23800, +1, 12.00),
    ], qty_lots=2)


def test_condor_economics():
    s = condor()
    assert s.net_credit == pytest.approx(52.55 - 8.00 + 61.90 - 12.00)  # 94.45
    assert s.call_width == 400 and s.put_width == 300
    assert s.max_loss_per_unit == pytest.approx(400 - 94.45)            # 305.55
    assert s.max_loss_rupees == pytest.approx(305.55 * 75 * 2)          # 45,832.50


def test_condor_pnl_marks():
    s = condor()
    entry_prices = {("CE", 24300): 52.55, ("CE", 24700): 8.0,
                    ("PE", 24100): 61.9, ("PE", 23800): 12.0}
    assert s.open_pnl_per_unit(entry_prices) == pytest.approx(0.0)
    # everything decays to half: short gains, wings lose
    half = {k: v / 2 for k, v in entry_prices.items()}
    assert s.open_pnl_per_unit(half) == pytest.approx(94.45 / 2)


def test_naked_short_unrepresentable():
    with pytest.raises(ValueError):
        Structure("condor", [
            Leg("CE", 24300, -1, 50.0), Leg("CE", 24200, +1, 80.0),  # wing INSIDE
            Leg("PE", 24100, -1, 60.0), Leg("PE", 23800, +1, 12.0),
        ], qty_lots=1)
    with pytest.raises(ValueError):
        Structure("condor", [  # only 3 legs
            Leg("CE", 24300, -1, 50.0),
            Leg("PE", 24100, -1, 60.0), Leg("PE", 23800, +1, 12.0),
        ], qty_lots=1)


def test_sell_fill_costs_exact():
    # Sell 150 units (2 lots) at mid 100: slip = min(max(100*0.008,0.05),1.5)=0.8
    f = C.execute(is_buy=False, mid_price=100.0, units=150)
    assert f.fill_price == pytest.approx(99.8)
    turnover = 99.8 * 150
    stt = 0.001 * turnover                                  # 14.88
    exch = 0.0003503 * turnover                             # 5.212464
    sebi = 10 / 1e7 * turnover                              # 0.01488
    gst = 0.18 * (20 + exch)                                # 4.538...
    assert f.charges == pytest.approx(20 + stt + exch + sebi + gst)
    assert f.slippage_rupees == pytest.approx(0.2 * 150)


def test_buy_fill_costs_exact():
    f = C.execute(is_buy=True, mid_price=5.0, units=75)
    assert f.fill_price == pytest.approx(5.05)              # slip clamped to 0.05
    turnover = 5.05 * 75
    stamp = 0.00003 * turnover
    exch = 0.0003503 * turnover
    sebi = 10 / 1e7 * turnover
    gst = 0.18 * (20 + exch)
    assert f.charges == pytest.approx(20 + stamp + exch + sebi + gst)


def test_expected_move_picker():
    """Synthetic expiry-morning chain: verify short placement at fwd +/- 1 EM and
    the farthest-feasible wing under max_loss <= 3x net credit."""
    import pandas as pd
    from backtest.strategy import StrategyConfig, pick_strikes

    ce = {24000: 100, 24050: 78, 24100: 58, 24150: 47, 24200: 40, 24250: 28,
          24300: 20, 24350: 15, 24400: 10, 24450: 7, 24500: 5}
    pe = {24000: 100, 23950: 78, 23900: 58, 23850: 47, 23800: 40, 23750: 28,
          23700: 20, 23650: 15, 23600: 10, 23550: 7, 23500: 5}
    rows = [{"option_type": "CE", "strike": float(k), "close": float(v),
             "delta": 0.5, "fwd": 24000.0} for k, v in ce.items()]
    rows += [{"option_type": "PE", "strike": float(k), "close": float(v),
              "delta": -0.5, "fwd": 24000.0} for k, v in pe.items()]
    chain = pd.DataFrame(rows)
    cfg = StrategyConfig({"strikes": {"kind": "condor", "mode": "expected_move",
                                      "em_mult": 1.0, "max_loss_mult": 3.0}})
    got = pick_strikes(cfg, chain)
    # EM = straddle at 24000 = 200 -> shorts snapped to 24200/23800 (gross 80).
    # D=300: net 80-5-5=70, loss 230 > 210 infeasible; D=250: net 66, loss 184 <= 198 OK.
    assert got == {"CE": (24200.0, 24450.0), "PE": (23800.0, 23550.0)}


def test_slippage_clamps():
    assert C.slippage_points(2.0) == 0.05     # floor
    assert C.slippage_points(100.0) == pytest.approx(0.2)  # 0.2%
    assert C.slippage_points(500.0) == 0.75  # cap
