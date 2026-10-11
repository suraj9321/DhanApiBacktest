"""Expiry-day directional hedged-condor, pyramided (Suraj spec, 2026-08-11).

Regime: Tuesday weekly-expiry only (0DTE), per [[feedback-tuesday-regime-window]].
Sizing: 1 lot per leg, per [[feedback-one-lot-only]].

Signal (rebuilt at each entry time):
  * S/R ladder = daily swings over last 4 weeks + 4wk H/L + prior-day H/L/C,
    merged with 5-min swings over last 1 week + current-week H/L; levels within
    0.15% clustered. Nearest resistance = lowest level > spot; support = highest < spot.
  * Direction = daily trend (close vs 20d SMA and its 5d slope) CONFIRMED by the
    5-min Supertrend(7,3) at the entry bar. up+up=bullish, down+down=bearish, else neutral.
  * Estimated move = daily ATR(14). SKIP the day if (near_res - near_sup) < ATR
    (expected move wider than the range we'd sell). Otherwise SKEW: bullish -> short
    put at nearest support, short call one level further out; bearish mirrors; neutral symmetric.

Structure: iron condor, short at the chosen S/R strikes, each short hedged with a
bought wing whose premium is nearest Rs.4 (defined risk, margin benefit, black-swan).

Execution: scale in 1 lot at 09:30 / 10:00 / 10:30 (adds are UNCONDITIONAL).
Management is on the AGGREGATE book: close everything when book open-P&L reaches
+70% of running net credit (target) or -150% (stop), else hard square-off 14:45.
DEFERRED (v1): if a target/stop fires mid-build, we flatten what's open, later
scheduled adds still go in and then ride to 14:45 with no re-arm.

Net credit is AFTER wing cost: (short_call+short_put) - (long_call+long_put).
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))            # scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # repo root
from src.backtest import costs
from src.backtest.data import MarketData
from src.backtest.structures import LOT_SIZE, Leg, Structure
from run_pivot_supertrend import five_min_bars, supertrend

CAPITAL = 800_000.0
WING_PREMIUM = 10.0    # Suraj 2026-08-11: was 4.0 — closer wing fits ATM±10 data better
ENTRY_TIMES = ["09:30", "10:00", "10:30"]
TARGET = None          # Suraj 2026-08-11: profit target REMOVED (was 0.90) — let theta run
STOP = 1.50
HARD_CLOSE = "14:55"   # Suraj 2026-08-11: was 14:45
SR_RANK = 1            # 0 = nearest S/R, 1 = 2nd-nearest from spot (Suraj 2026-08-11)
SMA_N, SLOPE_N, ATR_N = 20, 5, 14
SWING_K = 2            # bars each side for a swing pivot
CLUSTER_PCT = 0.0015   # merge levels within 0.15%
MARK_STEP = 5          # minutes between book marks


# ----------------------------- daily features --------------------------------
def daily_frame() -> pd.DataFrame:
    con = duckdb.connect()
    d = con.execute("""
        SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d, open, high, low, close
        FROM read_parquet('data/parquet/spot/nifty_daily/*/part.parquet')
        ORDER BY ts
    """).fetchdf()
    d["d"] = pd.to_datetime(d["d"]).dt.date
    pc = d["close"].shift(1)
    tr = np.maximum(d["high"] - d["low"],
                    np.maximum((d["high"] - pc).abs(), (d["low"] - pc).abs()))
    d["prev_close"] = pc
    d["atr"] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()
    d["sma"] = d["close"].rolling(SMA_N).mean()
    d["sma_slope"] = d["sma"] - d["sma"].shift(SLOPE_N)
    return d.reset_index(drop=True)


def swing_levels(highs, lows, k):
    lv = []
    for i in range(k, len(highs) - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            lv.append(highs[i])
        if lows[i] == min(lows[i - k:i + k + 1]):
            lv.append(lows[i])
    return lv


def cluster(levels):
    levels = sorted(v for v in levels if np.isfinite(v))
    out = []
    for v in levels:
        if out and abs(v - out[-1]) / out[-1] < CLUSTER_PCT:
            out[-1] = (out[-1] + v) / 2
        else:
            out.append(v)
    return out


def build_ladder(daily, bars5, d):
    dd = daily[daily["d"] < d].tail(20)          # 4 weeks of prior sessions
    if len(dd) < 10:
        return None, None
    lv = swing_levels(dd["high"].values, dd["low"].values, SWING_K)
    lv += [dd["high"].max(), dd["low"].min()]
    prev = dd.iloc[-1]
    lv += [prev["high"], prev["low"], prev["close"]]
    # 5-min swings, last 5 prior sessions
    b5 = bars5[bars5["d"] < d]
    days5 = sorted(b5["d"].unique())[-5:]
    b5 = b5[b5["d"].isin(days5)]
    if len(b5) > 2 * SWING_K:
        lv += swing_levels(b5["high"].values, b5["low"].values, SWING_K)
        lv += [b5["high"].max(), b5["low"].min()]
    return cluster(lv), prev


GAP_EPS = 0.0005   # 0.05% min move to count as a gap (avoids rounding noise)


def _has_3_consecutive(mask):
    run = 0
    for v in mask:
        run = run + 1 if v else 0
        if run >= 3:
            return True
    return False


def predict(daily, d):
    """Bull/bear call + estimated % move (Suraj 2026-08-11 layered rule).
    Base: majority of last 20 daily candles red -> bearish (else bullish).
    Override A: any 3 consecutive red (green) candles in the last 5 days.
    Override B (top priority): >=2 gap-downs (gap-ups) in the last 5 days.
    'neutral' is removed by design; always returns a direction."""
    dd = daily[daily["d"] < d]
    if len(dd) < 20:
        return None
    last20 = dd.tail(20)
    red20 = int((last20["close"] < last20["open"]).sum())
    green20 = int((last20["close"] > last20["open"]).sum())
    pred = "bearish" if red20 > green20 else "bullish"           # base
    last5 = dd.tail(5)
    if _has_3_consecutive((last5["close"] < last5["open"]).values):
        pred = "bearish"                                          # override A
    elif _has_3_consecutive((last5["close"] > last5["open"]).values):
        pred = "bullish"
    pc, op = last5["prev_close"].values, last5["open"].values
    gap_dn = int((op < pc * (1 - GAP_EPS)).sum())
    gap_up = int((op > pc * (1 + GAP_EPS)).sum())
    if gap_dn >= 2 and gap_up < 2:
        pred = "bearish"                                          # override B
    elif gap_up >= 2 and gap_dn < 2:
        pred = "bullish"
    row = dd.iloc[-1]
    return pred, float(row["atr"] / row["close"] * 100), float(row["close"])


# --------------------------- strike / wing picking ---------------------------
def nearest_levels(ladder, spot):
    res = [x for x in ladder if x > spot]
    sup = [x for x in ladder if x < spot]
    return (sorted(res), sorted(sup, reverse=True))  # ascending res, descending sup


def _lvl(seq, i):
    return seq[min(i, len(seq) - 1)]


def pick_levels(ladder, spot, moved_dir, confirmed):
    """Confirmed (moved our way): 2nd-closest S/R in the moved direction, closest
    in the other. U-turn (moved opposite): nearest in the moved direction,
    2nd-closest in the other. (Both collapse to: give the predicted side room,
    sell the other side tight.)"""
    res, sup = nearest_levels(ladder, spot)     # res asc, sup desc from spot
    if not res or not sup:
        return None
    moved_rank = 1 if confirmed else 0
    other_rank = 0 if confirmed else 1
    if moved_dir == "up":                        # moved side = resistance (call)
        call_lv, put_lv = _lvl(res, moved_rank), _lvl(sup, other_rank)
    else:                                        # moved side = support (put)
        call_lv, put_lv = _lvl(res, other_rank), _lvl(sup, moved_rank)
    return call_lv, put_lv


def strike_near(chain, opt, target, above=None):
    c = chain[chain["option_type"] == opt]
    if above is not None:
        c = c[c["strike"] > above] if opt == "CE" else c[c["strike"] < above]
    if c.empty:
        return None
    r = c.iloc[(c["strike"] - target).abs().argmin()]
    return float(r["strike"]), float(r["close"])


def wing_strike(chain, opt, short_strike):
    """OTM wing beyond the short (Suraj 2026-08-12): target ~Rs.WING_PREMIUM (10);
    if no strike beyond the short reaches that premium inside our ATM±10 window
    (short already deep OTM), fall back to the boundary/farthest strike instead of
    skipping. Tight wing where breach is likely, wide only where it isn't."""
    c = chain[chain["option_type"] == opt]
    c = c[c["strike"] > short_strike] if opt == "CE" else c[c["strike"] < short_strike]
    if c.empty:
        return None, False
    if float(c["close"].max()) >= WING_PREMIUM:
        r = c.iloc[(c["close"] - WING_PREMIUM).abs().argmin()]      # ~Rs.10 wing
    else:
        r = c.loc[c["strike"].idxmax()] if opt == "CE" else c.loc[c["strike"].idxmin()]  # boundary
    return (float(r["strike"]), float(r["close"])), True


def build_condor(chain, spot, ladder, moved_dir, confirmed):
    levels = pick_levels(ladder, spot, moved_dir, confirmed)
    if levels is None:
        return None, "no_sr"
    call_lv, put_lv = levels
    sc = strike_near(chain, "CE", call_lv, above=spot)
    sp = strike_near(chain, "PE", put_lv, above=spot)
    if sc is None or sp is None:
        return None, "no_short"
    (sc_k, sc_p), (sp_k, sp_p) = sc, sp
    cw, cw_ok = wing_strike(chain, "CE", sc_k)
    pw, pw_ok = wing_strike(chain, "PE", sp_k)
    if cw is None or pw is None:
        return None, "no_wing"
    legs = [
        Leg("CE", sc_k, -1, sc_p), Leg("CE", cw[0], +1, cw[1]),
        Leg("PE", sp_k, -1, sp_p), Leg("PE", pw[0], +1, pw[1]),
    ]
    try:
        st = Structure("condor", legs, qty_lots=1)
    except ValueError as e:
        return None, f"bad:{e}"
    return st, ("wing_ok" if (cw_ok and pw_ok) else "wing_edge")


# ------------------------------- pricing -------------------------------------
def price_all(md, d, tod, structures):
    px = {}
    for st in structures:
        for leg in st.legs:
            q = md.quote(d, tod, leg.opt_type, leg.strike)
            if q is None:
                return None
            px[(leg.opt_type, leg.strike)] = q
    return px


def leg_cash(md, d, tod, structures):
    """Cashflow (rupees, +receive/-pay) and charges/slippage to trade these legs
    in the direction that OPENS them (short=sell, long=buy)."""
    cash = chg = slp = 0.0
    for st in structures:
        for leg in st.legs:
            q = md.quote(d, tod, leg.opt_type, leg.strike)
            f = costs.execute(is_buy=(leg.side == +1), mid_price=q, units=LOT_SIZE)
            cash += (-1 if leg.side == +1 else +1) * f.fill_price * LOT_SIZE
            chg += f.charges
            slp += f.slippage_rupees
    return cash, chg, slp


def close_cash(md, d, tod, structures):
    """Cashflow to CLOSE (short=buy back, long=sell)."""
    cash = chg = slp = 0.0
    for st in structures:
        for leg in st.legs:
            q = md.quote(d, tod, leg.opt_type, leg.strike)
            f = costs.execute(is_buy=(leg.side == -1), mid_price=q, units=LOT_SIZE)
            cash += (+1 if leg.side == +1 else -1) * f.fill_price * LOT_SIZE
            chg += f.charges
            slp += f.slippage_rupees
    return cash, chg, slp


# ------------------------------- backtest ------------------------------------
def run(start_date, end_date):
    bars5 = supertrend(five_min_bars(), 7, 3.0)
    daily = daily_frame()
    md = MarketData(flag="week")
    expiry_days = [d for d in md.trading_days
                   if md.dte.get(d) == 0 and start_date <= d <= end_date]

    trades, skips = [], {"no_sr": 0, "no_short": 0, "no_wing": 0, "no_pred": 0,
                         "no_ladder": 0, "wing_edge": 0}
    marks = pd.date_range("09:30", HARD_CLOSE, freq=f"{MARK_STEP}min").strftime("%H:%M").tolist()

    for d in expiry_days:
        ladder, prev = build_ladder(daily, bars5, d)
        if not ladder:
            skips["no_ladder"] += 1
            continue
        pr = predict(daily, d)
        if pr is None:
            skips["no_pred"] += 1
            continue
        pred, est_pct, prior_close = pr
        # 9:30 move vs prediction -> confirm / u-turn (fixed for the day)
        ch930 = md.chain_at(d, "09:30")
        if len(ch930):
            spot930 = float(ch930["spot"].iloc[0])
        else:
            b = bars5[(bars5["d"] == d) & (bars5["signal_tod"] == "09:30")]
            spot930 = float(b["close"].iloc[0]) if len(b) else prior_close
        moved_dir = "up" if spot930 >= prior_close else "down"
        confirmed = (pred == "bullish" and moved_dir == "up") or \
                    (pred == "bearish" and moved_dir == "down")
        case = "confirm" if confirmed else "uturn"

        open_st = []
        triggered = False
        day_rows = []
        for tod in marks:
            # scheduled add (unconditional)
            if tod in ENTRY_TIMES:
                chain = md.chain_at(d, tod)
                if len(chain):
                    spot = float(chain["spot"].iloc[0])
                    st, why = build_condor(chain, spot, ladder, moved_dir, confirmed)
                    if st is None:
                        skips[why if why in skips else "no_short"] = skips.get(why, 0) + 1
                    else:
                        if why == "wing_edge":
                            skips["wing_edge"] += 1
                        cash, chg, slp = leg_cash(md, d, tod, [st])
                        st.field_notes.update(entry_tod=tod, dirn=pred, case=case,
                                              entry_cash=cash, chg=chg, slp=slp)
                        open_st.append(st)
            if not open_st:
                continue
            px = price_all(md, d, tod, open_st)
            if px is None:
                continue
            total_credit = sum(s.net_credit for s in open_st)
            book_pnl = sum(s.open_pnl_per_unit(px) for s in open_st) * LOT_SIZE
            hit = None
            if not triggered and total_credit > 0:
                if TARGET is not None and book_pnl >= TARGET * total_credit * LOT_SIZE:
                    hit = "target"
                elif book_pnl <= -STOP * total_credit * LOT_SIZE:
                    hit = "stop"
            if hit or tod == HARD_CLOSE:
                reason = hit or "hard_close"
                for st in open_st:
                    ccash, cchg, cslp = close_cash(md, d, tod, [st])
                    pnl = (st.field_notes["entry_cash"] + ccash) - (st.field_notes["chg"] + cchg)
                    day_rows.append({
                        "d": d, "direction": st.field_notes["dirn"],
                        "case": st.field_notes["case"],
                        "entry_tod": st.field_notes["entry_tod"],
                        "exit_tod": tod, "reason": reason,
                        "short_call": st.short_strikes["CE"], "short_put": st.short_strikes["PE"],
                        "credit_pts": st.net_credit, "max_loss": st.max_loss_rupees,
                        "gross": st.field_notes["entry_cash"] + ccash,
                        "charges": st.field_notes["chg"] + cchg,
                        "slippage": st.field_notes["slp"] + cslp,
                        "pnl": pnl,
                    })
                open_st = []
                if hit:
                    triggered = True   # v1: no re-arm; later adds ride to hard close
        trades.extend(day_rows)

    return pd.DataFrame(trades), skips, md, len(expiry_days)


def summarize(tr, skips, n_days):
    if tr.empty:
        print("no trades"); print("skips", skips); return
    pnl = tr["pnl"]; wins = pnl[pnl > 0]; losses = pnl[pnl <= 0]
    daily = tr.groupby("d")["pnl"].sum()
    eq = CAPITAL + daily.cumsum(); dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    dret = daily / CAPITAL
    sharpe = dret.mean() / dret.std() * np.sqrt(252) if dret.std() > 0 else float("nan")
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    print(f"\n=== Expiry-day directional condor (Tue regime) ===")
    print(f"  expiry days in window   {n_days}")
    print(f"  condors (positions)     {len(tr)}   trading days {daily.index.nunique()}")
    print(f"  net P&L (Rs)            {pnl.sum():,.0f}   ({100*pnl.sum()/CAPITAL:+.2f}% on 8L)")
    print(f"  win rate (per condor)   {100*(pnl>0).mean():.1f}%")
    print(f"  day win rate            {100*(daily>0).mean():.1f}%")
    print(f"  avg win / avg loss      {wins.mean():,.0f} / {losses.mean() if len(losses) else 0:,.0f}")
    print(f"  profit factor           {pf:.2f}   sharpe(daily) {sharpe:.2f}   maxDD {dd:.2f}%")
    print(f"  worst / best condor     {pnl.min():,.0f} / {pnl.max():,.0f}")
    print(f"  gross / costs           {tr['gross'].sum():,.0f} / {(tr['charges']+tr['slippage']).sum():,.0f}")
    print(f"  direction mix           {tr['direction'].value_counts().to_dict()}")
    for dn in ("bullish", "bearish", "neutral"):
        s = tr[tr.direction == dn]["pnl"]
        if len(s):
            print(f"    {dn:8s} n={len(s):3d}  pnl {s.sum():>9,.0f}  win {100*(s>0).mean():.0f}%")
    if "case" in tr.columns:
        print(f"  case mix                {tr['case'].value_counts().to_dict()}")
        for cs in ("confirm", "uturn"):
            s = tr[tr.case == cs]["pnl"]
            if len(s):
                print(f"    {cs:8s} n={len(s):3d}  pnl {s.sum():>9,.0f}  win {100*(s>0).mean():.0f}%")
    print(f"  exit reasons            {tr['reason'].value_counts().to_dict()}")
    print(f"  skips                   {skips}")


def main():
    start = pd.Timestamp("2025-08-29").date()   # Tuesday-expiry regime start
    end = pd.Timestamp("2026-07-16").date()
    print(f"Window {start} .. {end}  (Tuesday 0DTE only)")
    tr, skips, md, n = run(start, end)
    summarize(tr, skips, n)
    out = Path("data/backtest_expiry_condor_v2_trades.parquet")
    tr.to_parquet(out)
    print(f"\nSaved -> {out}   quote fallbacks {md.fallback_counts}")


if __name__ == "__main__":
    main()
