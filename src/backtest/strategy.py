"""Strategy = configuration. A variant is a YAML file; this module is the schema
plus pure evaluation functions (no market access, no portfolio mutation).

Config schema (configs/*.yaml):

  name: weekly_v01
  flag: week                 # week | month
  entry:
    dte: 1                   # sessions remaining at entry
    tod: "09:20"
    gates:                   # all must pass; omitted = not applied
      vrp_week_min: 0.0
      vrp_z_min: null
      iv_rank_min: null
  strikes:
    kind: condor             # condor | fly
    short_delta: 0.15        # target |delta| of short legs (fly: shorts at ATM)
    put_wing_pts: 300        # wing distance beyond short strike
    call_wing_pts: 400
    # -- OR expected-move mode (expiry-day condor) --
    mode: expected_move      # shorts at fwd +/- em_mult * ATM-straddle price
    em_mult: 1.0
    max_loss_mult: 3.0       # wings: farthest distance with width - credit <= mult * credit
  exits:
    profit_target_pct: 50    # % of net credit captured
    stop_multiple: 2.0       # loss >= multiple * credit
    delta_breach: 0.30       # |short-leg delta| threshold
    hard:  {dte: 0, tod: "13:15"}
  sizing:
    risk_pct_per_trade: 2.0  # of trading capital, at max structural loss
  eval_step_min: 5
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .structures import Leg, Structure


@dataclass
class StrategyConfig:
    raw: dict

    @classmethod
    def load(cls, path: str | Path) -> "StrategyConfig":
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def name(self):
        return self.raw["name"]

    @property
    def flag(self):
        return self.raw["flag"]


def gates_pass(cfg: StrategyConfig, signal_row, morning_iv: float | None) -> bool:
    if signal_row is None:
        return False
    g = cfg["entry"].get("gates") or {}
    import numpy as np
    fields = {"vrp_week": signal_row.get("vrp_week"),
              "vrp_month": signal_row.get("vrp_month"),
              "vrp_z": signal_row.get("vrp_z"),
              "iv_rank": signal_row.get("iv_rank_1y")}
    for name, value in fields.items():
        lo, hi = g.get(f"{name}_min"), g.get(f"{name}_max")
        if lo is None and hi is None:
            continue
        if value is None or not np.isfinite(value):
            return False
        if lo is not None and value < lo:
            return False
        if hi is not None and value > hi:
            return False
    return True


def pick_strikes_expected_move(cfg: StrategyConfig, chain) -> dict | None:
    """Expiry-day condor: shorts at fwd +/- em_mult * ATM-straddle price,
    wings at the FARTHEST symmetric distance D such that the structure's
    max loss (D - net_credit) stays <= max_loss_mult * net_credit.

    Farthest-first scan resolves the circularity that wing price feeds back
    into net credit: the first feasible D is the cheapest protective wing
    honouring the loss cap. Returns None if no wing distance is feasible.
    """
    import numpy as np
    s = cfg["strikes"]
    px = {}
    for opt in ("CE", "PE"):
        side = chain[(chain["option_type"] == opt) & chain["close"].notna()]
        if side.empty:
            return None
        px[opt] = side.groupby("strike")["close"].last()
    fwd = float(chain["fwd"].median())
    common = px["CE"].index.intersection(px["PE"].index).values
    if len(common) == 0:
        return None
    atm_k = common[np.abs(common - fwd).argmin()]
    em = float(px["CE"][atm_k] + px["PE"][atm_k])  # straddle = E|S_T - K_atm|
    if em <= 0:
        return None
    ce_strikes = np.array(sorted(k for k in px["CE"].index if k > fwd))
    pe_strikes = np.array(sorted(k for k in px["PE"].index if k < fwd))
    if len(ce_strikes) == 0 or len(pe_strikes) == 0:
        return None
    short_ce = float(ce_strikes[np.abs(ce_strikes - (fwd + s["em_mult"] * em)).argmin()])
    short_pe = float(pe_strikes[np.abs(pe_strikes - (fwd - s["em_mult"] * em)).argmin()])
    gross = float(px["CE"][short_ce] + px["PE"][short_pe])
    mult = s.get("max_loss_mult", 3.0)
    ce_dists = {k - short_ce for k in px["CE"].index if k > short_ce}
    pe_dists = {short_pe - k for k in px["PE"].index if k < short_pe}
    for dist in sorted(ce_dists & pe_dists, reverse=True):
        wing_ce, wing_pe = short_ce + dist, short_pe - dist
        net = gross - float(px["CE"][wing_ce] + px["PE"][wing_pe])
        if net <= 0:
            continue
        if dist - net <= mult * net:
            return {"CE": (short_ce, wing_ce), "PE": (short_pe, wing_pe)}
    return None


def pick_strikes(cfg: StrategyConfig, chain) -> dict | None:
    """Choose short strikes by delta target and wings by point distance.

    chain: rows at the entry tick with option_type, strike, close, delta.
    Returns {"CE": (short, wing), "PE": (short, wing)} or None if unusable.
    """
    s = cfg["strikes"]
    if s.get("mode") == "expected_move":
        return pick_strikes_expected_move(cfg, chain)
    out = {}
    for opt, sign in (("CE", +1), ("PE", -1)):
        side = chain[(chain["option_type"] == opt) & chain["delta"].notna()]
        if side.empty:
            return None
        if s["kind"] == "fly":
            atm_idx = (side["strike"] - side["fwd"]).abs().idxmin()
            short_k = float(side.loc[atm_idx, "strike"])
        else:
            tgt = s["short_delta"] * sign
            short_k = float(side.loc[(side["delta"] - tgt).abs().idxmin(), "strike"])
        wing_pts = s["call_wing_pts"] if opt == "CE" else s["put_wing_pts"]
        want = short_k + wing_pts if opt == "CE" else short_k - wing_pts
        avail = side["strike"].values
        wing_k = float(avail[abs(avail - want).argmin()])
        outside = wing_k > short_k if opt == "CE" else wing_k < short_k
        if not outside:
            return None  # wing would not be protective; skip this entry
        out[opt] = (short_k, wing_k)
    return out


def build_structure(cfg: StrategyConfig, strikes: dict, fills: dict, qty_lots: int,
                    entry_ts) -> Structure:
    """fills: {(opt, strike): fill_price} from the execution engine."""
    legs = []
    for opt in ("CE", "PE"):
        short_k, wing_k = strikes[opt]
        legs.append(Leg(opt, short_k, -1, fills[(opt, short_k)]))
        legs.append(Leg(opt, wing_k, +1, fills[(opt, wing_k)]))
    return Structure(cfg["strikes"]["kind"], legs, qty_lots, entry_ts=entry_ts)


def exit_reason(cfg: StrategyConfig, structure: Structure, prices: dict,
                short_deltas: dict, dte: int, tod: str) -> str | None:
    """First matching exit rule, else None. Order: hard > stop > delta > target."""
    e = cfg["exits"]
    hard = e.get("hard") or {}
    if dte < hard.get("dte", 0) or (dte == hard.get("dte", 0) and tod >= hard.get("tod", "15:15")):
        return "hard_time"
    pnl = structure.open_pnl_per_unit(prices)
    credit = structure.net_credit
    if e.get("stop_multiple") is not None and pnl <= -e["stop_multiple"] * credit:
        return "stop"
    db = e.get("delta_breach")
    if db is not None and any(abs(d) >= db for d in short_deltas.values() if d is not None):
        return "delta_breach"
    tp = e.get("profit_target_pct")
    if tp is not None and pnl >= credit * tp / 100.0:
        return "target"
    return None
