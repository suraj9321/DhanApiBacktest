"""Option-liquidity scorecard: rank underlyings by how cheap/deep their options
are to trade, using the LIVE Dhan Option Chain API (bid-ask, OI, volume).

For each underlying it pulls the nearest-expiry chain, looks at the ATM ± window
strikes (both CE and PE), and measures:
  • bid-ask spread as % of mid  (the real per-trade execution cost — weighted most)
  • open interest and traded volume  (depth / participation)
  • how many near-ATM strikes are actually tight+liquid
then blends them into a 0-100 liquidity score and ranks.

Symbols resolve to Dhan security IDs via the public scrip master (equities →
NSE_EQ, indices → IDX_I). Bid/ask/volume are only meaningful DURING market hours
(09:15-15:30 IST); OI persists overnight. Rate-limited to the Option Chain API's
1 request / 3 seconds.

Usage:
  python scripts/liquidity_scorecard.py                 # default index+stock set
  python scripts/liquidity_scorecard.py --symbols NIFTY,RELIANCE,SBIN --window 5
  python scripts/liquidity_scorecard.py --html data/liquidity_scorecard.html
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline.dhan_client import DhanClient, DhanAPIError

SCRIP_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
SCRIP_CACHE = Path("data/raw/scrip_master.csv")
OC_MIN_INTERVAL = 3.1          # Option Chain API: 1 req / 3s
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
DEFAULT_SYMBOLS = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "AXISBANK",
    "KOTAKBANK", "BAJFINANCE", "TATAMOTORS", "TATASTEEL", "ADANIENT", "LT",
    "ITC", "BHARTIARTL", "HINDALCO", "MARUTI", "SUNPHARMA", "VEDL", "WIPRO",
]
TIGHT_SPREAD_PCT = 1.0         # a strike counts as "liquid" if spread ≤ this and oi>0


# ------------------------------ symbol resolver ------------------------------
def load_scrip_master(max_age_h: float = 24.0):
    if not (SCRIP_CACHE.exists()
            and (time.time() - SCRIP_CACHE.stat().st_mtime) < max_age_h * 3600):
        SCRIP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(SCRIP_URL, timeout=90)
        r.raise_for_status()
        SCRIP_CACHE.write_text(r.text)
    rows = list(csv.DictReader(io.StringIO(SCRIP_CACHE.read_text())))
    eq, idx = {}, {}
    for x in rows:
        if x.get("SEM_EXM_EXCH_ID") != "NSE":
            continue
        sym = x.get("SEM_TRADING_SYMBOL", "")
        sid = x.get("SEM_SMST_SECURITY_ID", "")
        if x.get("SEM_SEGMENT") == "E" and x.get("SEM_INSTRUMENT_NAME") == "EQUITY":
            eq.setdefault(sym, sid)
        elif x.get("SEM_SEGMENT") == "I":
            idx.setdefault(sym, sid)
    return eq, idx


def resolve(symbol, eq, idx):
    """-> (security_id:int, underlying_seg, is_index) or None."""
    if symbol in INDEX_SYMBOLS and symbol in idx:
        return int(idx[symbol]), "IDX_I", True
    if symbol in eq:
        return int(eq[symbol]), "NSE_EQ", False
    if symbol in idx:
        return int(idx[symbol]), "IDX_I", True
    return None


# ------------------------------ chain + metrics ------------------------------
_last_oc_call = [0.0]


def _oc_throttle():
    wait = OC_MIN_INTERVAL - (time.monotonic() - _last_oc_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_oc_call[0] = time.monotonic()


def fetch_chain(client, scrip, seg):
    _oc_throttle()
    el = client.post("/optionchain/expirylist", {"UnderlyingScrip": scrip, "UnderlyingSeg": seg})
    exps = el.get("data") or []
    if not exps:
        return None
    today = date.today().isoformat()
    expiry = next((e for e in sorted(exps) if e >= today), sorted(exps)[0])
    _oc_throttle()
    oc = client.post("/optionchain",
                     {"UnderlyingScrip": scrip, "UnderlyingSeg": seg, "Expiry": expiry})
    d = oc.get("data", {})
    return d.get("last_price"), expiry, d.get("oc", {})


def _spread_pct(leg):
    if not leg:
        return None, None
    bid, ask = leg.get("top_bid_price") or 0, leg.get("top_ask_price") or 0
    if bid <= 0 or ask <= 0 or ask < bid:
        return None, None
    mid = (bid + ask) / 2
    return (ask - bid), (ask - bid) / mid * 100 if mid > 0 else None


def score_underlying(last_price, oc, window):
    if not oc or not last_price:
        return None
    strikes = sorted(float(k) for k in oc.keys())
    atm = min(strikes, key=lambda s: abs(s - last_price))
    ai = strikes.index(atm)
    near = strikes[max(0, ai - window): ai + window + 1]
    spreads, oi_tot, vol_tot, liquid, legs = [], 0, 0, 0, 0
    atm_spr = []
    for s in near:
        rec = oc.get(f"{s:.6f}") or oc.get(f"{s:.1f}") or {}
        for side in ("ce", "pe"):
            leg = rec.get(side)
            if not leg:
                continue
            oi_tot += leg.get("oi") or 0
            vol_tot += leg.get("volume") or 0
            _, spct = _spread_pct(leg)
            if spct is not None:
                spreads.append(spct)
                legs += 1
                if spct <= TIGHT_SPREAD_PCT and (leg.get("oi") or 0) > 0:
                    liquid += 1
                if s == atm:
                    atm_spr.append(spct)
    if not spreads:
        return {"atm": atm, "n_legs": 0, "med_spread": None, "atm_spread": None,
                "oi": oi_tot, "vol": vol_tot, "liquid_strikes": 0}
    spreads.sort()
    return {
        "atm": atm, "n_legs": legs,
        "med_spread": spreads[len(spreads) // 2],
        "atm_spread": sum(atm_spr) / len(atm_spr) if atm_spr else None,
        "oi": oi_tot, "vol": vol_tot, "liquid_strikes": liquid,
    }


# ------------------------------ scoring / output -----------------------------
def pct_rank(values):
    """value -> [0,1] percentile rank (ties share mean rank); None -> 0."""
    clean = sorted(v for v in values if v is not None)
    n = len(clean)
    if n <= 1:
        return {v: 0.5 for v in values}
    out = {}
    for v in values:
        if v is None:
            out[v] = 0.0
        else:
            out[v] = sum(1 for c in clean if c < v) / (n - 1)
    return out


def rank_all(results):
    rows = [r for r in results if r["metrics"] and r["metrics"]["med_spread"] is not None]
    if not rows:
        return results
    # lower spread better -> rank on negative spread
    sp = pct_rank([-r["metrics"]["med_spread"] for r in rows])
    import math
    oi = pct_rank([math.log10(max(r["metrics"]["oi"], 1)) for r in rows])
    vo = pct_rank([math.log10(max(r["metrics"]["vol"], 1)) for r in rows])
    for r in rows:
        s = 100 * (0.5 * sp[-r["metrics"]["med_spread"]]
                   + 0.25 * oi[math.log10(max(r["metrics"]["oi"], 1))]
                   + 0.25 * vo[math.log10(max(r["metrics"]["vol"], 1))])
        r["score"] = round(s, 1)
    rows.sort(key=lambda r: r["score"], reverse=True)
    tail = [r for r in results if not (r["metrics"] and r["metrics"]["med_spread"] is not None)]
    return rows + tail


def print_table(ranked, window):
    print(f"\n{'#':>2} {'symbol':<12}{'type':<6}{'LTP':>10}{'expiry':>12}"
          f"{'ATM spr%':>9}{'med spr%':>9}{'liq strk':>9}{'OI':>13}{'volume':>14}{'score':>7}")
    print("-" * 116)
    for i, r in enumerate(ranked, 1):
        m = r["metrics"]
        if not m:
            print(f"{i:>2} {r['symbol']:<12}{'—':<6}{'(no chain / not F&O)':>40}")
            continue
        def f(x, d=2): return f"{x:.{d}f}" if x is not None else "—"
        print(f"{i:>2} {r['symbol']:<12}{('idx' if r['is_index'] else 'stk'):<6}"
              f"{r['ltp']:>10.1f}{r['expiry'][5:]:>12}{f(m['atm_spread']):>9}{f(m['med_spread']):>9}"
              f"{m['liquid_strikes']:>9}{m['oi']:>13,}{m['vol']:>14,}{r.get('score','—'):>7}")
    print(f"\n(ATM ±{window} strikes, both CE & PE. Lower spread% + higher OI/volume = more "
          f"liquid. Score: 50% spread, 25% OI, 25% volume, percentile-blended.)")


def build_html(ranked, window, stamp, market_note):
    POS, WARN, LINE, MUTE = "#1a9e76", "#d1495b", "#3b6ea5", "#8a94a6"
    def bar(score):
        w = max(0, min(100, score or 0))
        col = POS if w >= 66 else ("#e0a030" if w >= 33 else WARN)
        return (f'<div class="barwrap"><div class="bar" style="width:{w}%;background:{col}"></div>'
                f'<span>{score:.0f}</span></div>')
    trows = ""
    for i, r in enumerate(ranked, 1):
        m = r["metrics"]
        if not m or m["med_spread"] is None:
            trows += (f'<tr class="dim"><td>{i}</td><td>{r["symbol"]}</td>'
                      f'<td colspan="8">no chain / not in F&O</td></tr>')
            continue
        sp = m["med_spread"]
        spcls = "good" if sp <= 0.5 else ("mid" if sp <= 1.5 else "bad")
        trows += (f'<tr><td>{i}</td><td class="sym">{r["symbol"]}</td>'
                  f'<td><span class="pill {"idx" if r["is_index"] else "stk"}">{"index" if r["is_index"] else "stock"}</span></td>'
                  f'<td class="num">{r["ltp"]:,.1f}</td><td class="num muted">{r["expiry"][5:]}</td>'
                  f'<td class="num {spcls}">{m["atm_spread"]:.2f}%</td>'
                  f'<td class="num {spcls}">{sp:.2f}%</td>'
                  f'<td class="num">{m["liquid_strikes"]}</td>'
                  f'<td class="num">{m["oi"]:,}</td><td class="num">{m["vol"]:,}</td>'
                  f'<td>{bar(r.get("score"))}</td></tr>')
    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--border:#e6e9ef;--hl:#f0f3f8;--good:#1a9e76;--mid:#c98a1a;--bad:#d1495b;--idx:#3b6ea5;--stk:#7a5bd0;}
    @media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--border:#232c38;--hl:#1b2430;--good:#3cba90;--mid:#e0a030;--bad:#e0647a;--idx:#5b8fd0;--stk:#a98be6;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--border:#232c38;--hl:#1b2430;--good:#3cba90;--mid:#e0a030;--bad:#e0647a;--idx:#5b8fd0;--stk:#a98be6;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--border:#e6e9ef;--hl:#f0f3f8;--good:#1a9e76;--mid:#c98a1a;--bad:#d1495b;--idx:#3b6ea5;--stk:#7a5bd0;}
    *{box-sizing:border-box}
    body{background:var(--bg);color:var(--ink);font:14.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 56px}
    .wrap{max-width:1000px;margin:0 auto} h1{font-size:22px;margin:0 0 2px}
    .sub{color:var(--muted);margin:0 0 6px;font-size:13px}
    .note{color:var(--mid);font-size:12.5px;margin:0 0 16px}
    .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:6px 8px;overflow-x:auto}
    table{width:100%;border-collapse:collapse;font-size:13px;min-width:820px}
    th,td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}
    th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em;position:sticky;top:0;background:var(--card)}
    th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left}
    td.sym{font-weight:650} tr:hover td{background:var(--hl)}
    .num{font-variant-numeric:tabular-nums} .muted{color:var(--muted)}
    .good{color:var(--good)} .mid{color:var(--mid)} .bad{color:var(--bad)}
    tr.dim td{color:var(--muted)}
    .pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11px;font-weight:600;color:#fff}
    .pill.idx{background:var(--idx)} .pill.stk{background:var(--stk)}
    .barwrap{display:flex;align-items:center;gap:6px;min-width:96px}
    .bar{height:8px;border-radius:4px;min-width:2px} .barwrap span{font-size:12px;color:var(--ink2);width:22px;text-align:right}
    .legend{color:var(--muted);font-size:12px;margin-top:12px;line-height:1.6}
    """
    return (f'<title>Option liquidity scorecard</title><style>{css}</style>'
            f'<div class="wrap"><h1>Option liquidity scorecard — Nifty F&O universe</h1>'
            f'<p class="sub">Live Dhan option chain · nearest expiry · ATM ±{window} strikes (CE+PE) · {stamp}</p>'
            f'<p class="note">{market_note}</p>'
            f'<div class="card"><table><thead><tr><th>#</th><th>Symbol</th><th>Type</th>'
            f'<th>LTP</th><th>Expiry</th><th>ATM spr</th><th>Med spr</th><th>Liq strk</th>'
            f'<th>Open int</th><th>Volume</th><th>Score</th></tr></thead><tbody>{trows}</tbody></table></div>'
            f'<div class="legend"><b>Spread</b> = (ask−bid)/mid, % — the real per-trade cost; '
            f'<span class="good">≤0.5%</span> tight, <span class="bad">&gt;1.5%</span> wide. '
            f'<b>Liq strk</b> = near-ATM strikes with spread ≤1% and OI&gt;0. '
            f'<b>Score</b> (0-100) blends spread 50% / OI 25% / volume 25%, percentile-ranked within this set. '
            f'Bid/ask/volume are live-market values; run during 09:15–15:30 IST. Nearest expiry differs by tenor '
            f'(indices weekly, stocks monthly) — compare within type. Not investment advice.</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma-separated; default = index+top-stock set")
    ap.add_argument("--window", type=int, default=5, help="ATM ± strikes to sample")
    ap.add_argument("--html", default="data/liquidity_scorecard.html")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else DEFAULT_SYMBOLS
    print("Loading scrip master ...")
    eq, idx = load_scrip_master()
    client = DhanClient()

    results = []
    for sym in symbols:
        res = resolve(sym, eq, idx)
        if not res:
            print(f"  {sym:<12} unresolved (not in NSE scrip master)")
            results.append({"symbol": sym, "is_index": False, "metrics": None})
            continue
        scrip, seg, is_index = res
        try:
            chain = fetch_chain(client, scrip, seg)
        except DhanAPIError as e:
            print(f"  {sym:<12} API error: {str(e)[:70]}")
            results.append({"symbol": sym, "is_index": is_index, "metrics": None})
            continue
        if not chain:
            print(f"  {sym:<12} no expiries / not F&O")
            results.append({"symbol": sym, "is_index": is_index, "metrics": None})
            continue
        ltp, expiry, oc = chain
        m = score_underlying(ltp, oc, args.window)
        print(f"  {sym:<12} LTP {ltp:>9.1f}  exp {expiry}  "
              f"medspr {m['med_spread'] if m and m['med_spread'] else float('nan'):.2f}%  "
              f"OI {m['oi']:,}" if m else f"  {sym:<12} empty")
        results.append({"symbol": sym, "is_index": is_index, "ltp": ltp,
                        "expiry": expiry, "metrics": m})

    ranked = rank_all(results)
    print_table(ranked, args.window)

    # market-hours sanity: are spreads/volumes present?
    live = [r for r in ranked if r.get("metrics") and r["metrics"].get("med_spread")]
    any_vol = any(r["metrics"]["vol"] > 0 for r in live)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    market_note = ("" if any_vol else
                   "⚠ All volumes are zero — market appears closed. Spreads/volume are only "
                   "meaningful during 09:15–15:30 IST; OI is still valid.")
    Path(args.html).write_text(build_html(ranked, args.window, stamp, market_note))
    print(f"\nWrote {args.html}")


if __name__ == "__main__":
    main()
