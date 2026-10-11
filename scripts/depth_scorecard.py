"""Cash-equity order-book DEPTH scorecard for Nifty 50 + Nifty Next 50.

Pulls LIVE 5-level market depth via the Dhan quote API (`POST /marketfeed/quote`,
batched — one call for the whole universe) and reports, per stock:
  • best bid/ask spread (% of mid)
  • top-of-book size (₹ at the best bid/ask)
  • top-5-level depth (₹ resting within the 5 visible levels, both sides)
  • total pending book (₹) = (buy_qty + sell_qty) × LTP across the whole book
Then summarizes by tier (Nifty 50 vs Next 50).

Depth is a LIVE snapshot — only meaningful during market hours (09:15-15:30 IST);
outside them the book collapses and the script says so. Symbols resolve to Dhan
security IDs via the public scrip master. Constituent lists are approximate
(edit the sets below as index membership changes).

Usage: python scripts/depth_scorecard.py [--html data/depth_scorecard.html]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # repo root
from liquidity_scorecard import load_scrip_master, resolve
from src.pipeline.dhan_client import DhanClient, DhanAPIError

# --- Approximate constituents (edit as membership changes) -------------------
NIFTY50 = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE
BAJAJFINSV BEL BHARTIARTL BPCL BRITANNIA CIPLA COALINDIA DRREDDY EICHERMOT GRASIM
HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO HINDUNILVR ICICIBANK INDUSINDBK INFY
ITC JSWSTEEL KOTAKBANK LT LTIM M&M MARUTI NESTLEIND NTPC ONGC POWERGRID RELIANCE
SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATASTEEL TCS TECHM TITAN TRENT
ULTRACEMCO WIPRO""".split()
NEXT50 = """ABB ADANIENSOL ADANIGREEN ADANIPOWER AMBUJACEM BAJAJHLDNG BANKBARODA
BERGEPAINT BOSCHLTD CANBK CHOLAFIN COLPAL DABUR DIVISLAB DLF DMART GAIL GODREJCP
GODREJPROP HAL HAVELLS ICICIGI ICICIPRULI INDIGO IOC IRFC JINDALSTEL JSWENERGY
JIOFIN LICI LODHA MOTHERSON MAXHEALTH NAUKRI PFC PIDILITIND PNB POLYCAB RECLTD
SIEMENS SRF TATAPOWER TORNTPHARM TVSMOTOR UNITDSPR VBL VEDL ZYDUSLIFE ETERNAL
GAIL""".split()


def batch_quote(client, ids):
    """One /marketfeed/quote call for a list of NSE_EQ security ids."""
    body = {"NSE_EQ": ids}
    out = client.post("/marketfeed/quote", body)
    return (out.get("data", {}) or {}).get("NSE_EQ", {}) or {}


def depth_metrics(rec):
    ltp = rec.get("last_price") or 0
    dep = rec.get("depth", {}) or {}
    buys, sells = dep.get("buy", []) or [], dep.get("sell", []) or []
    bb = buys[0]["price"] if buys and buys[0].get("price") else 0
    ba = sells[0]["price"] if sells and sells[0].get("price") else 0
    spread_pct = ((ba - bb) / ((ba + bb) / 2) * 100) if bb > 0 and ba > 0 and ba >= bb else None
    top_bid_val = (buys[0]["price"] * buys[0]["quantity"]) if bb > 0 else 0
    top_ask_val = (sells[0]["price"] * sells[0]["quantity"]) if ba > 0 else 0
    d5 = sum(l["price"] * l["quantity"] for l in buys if l.get("price")) \
        + sum(l["price"] * l["quantity"] for l in sells if l.get("price"))
    total_book = ((rec.get("buy_quantity") or 0) + (rec.get("sell_quantity") or 0)) * ltp
    return {
        "ltp": ltp, "spread_pct": spread_pct,
        "top_bid_val": top_bid_val, "top_ask_val": top_ask_val,
        "depth5": d5, "total_book": total_book,
        "closed": not (bb > 0 and ba > 0),
    }


def cr(x):
    return f"{x/1e7:.2f}"  # rupees -> crore


def run(client, tier_syms, eq, idx):
    resolved, unresolved = {}, []
    for s in tier_syms:
        r = resolve(s, eq, idx)
        if r:
            resolved[int(r[0])] = s
        else:
            unresolved.append(s)
    quotes = batch_quote(client, list(resolved.keys())) if resolved else {}
    rows = []
    for sid, sym in resolved.items():
        rec = quotes.get(str(sid))
        if not rec:
            unresolved.append(sym)
            continue
        m = depth_metrics(rec)
        m["symbol"] = sym
        rows.append(m)
    return rows, unresolved


def summarize(name, rows):
    live = [r for r in rows if not r["closed"] and r["spread_pct"] is not None]
    print(f"\n=== {name} ({len(rows)} resolved, {len(live)} with live book) ===")
    if not live:
        print("  no live depth (market closed?)")
        return
    live.sort(key=lambda r: r["total_book"], reverse=True)
    print(f"  {'symbol':<12}{'LTP':>9}{'spread%':>9}{'top₹bid(cr)':>12}"
          f"{'5lvl(cr)':>10}{'book(cr)':>10}")
    for r in live:
        print(f"  {r['symbol']:<12}{r['ltp']:>9.1f}{r['spread_pct']:>9.3f}"
              f"{cr(r['top_bid_val']):>12}{cr(r['depth5']):>10}{cr(r['total_book']):>10}")
    sp = sorted(r["spread_pct"] for r in live)
    bk = sorted(r["total_book"] for r in live)
    print(f"  MEDIAN spread {sp[len(sp)//2]:.3f}%   MEDIAN book ₹{cr(bk[len(bk)//2])} cr")


def build_html(tiers, stamp, closed_note):
    def rowshtml(rows):
        live = [r for r in rows if not r["closed"] and r["spread_pct"] is not None]
        live.sort(key=lambda r: r["total_book"], reverse=True)
        out = ""
        for i, r in enumerate(live, 1):
            sp = r["spread_pct"]
            cls = "good" if sp <= 0.05 else ("mid" if sp <= 0.15 else "bad")
            out += (f'<tr><td>{i}</td><td class="sym">{r["symbol"]}</td>'
                    f'<td class="num">{r["ltp"]:,.1f}</td>'
                    f'<td class="num {cls}">{sp:.3f}%</td>'
                    f'<td class="num">{cr(r["top_bid_val"])}</td>'
                    f'<td class="num">{cr(r["depth5"])}</td>'
                    f'<td class="num">{cr(r["total_book"])}</td></tr>')
        return out or '<tr class="dim"><td colspan="7">no live book (market closed)</td></tr>'
    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--border:#e6e9ef;--hl:#f0f3f8;--good:#1a9e76;--mid:#c98a1a;--bad:#d1495b;}
    @media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--border:#232c38;--hl:#1b2430;--good:#3cba90;--mid:#e0a030;--bad:#e0647a;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--border:#232c38;--hl:#1b2430;--good:#3cba90;--mid:#e0a030;--bad:#e0647a;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--border:#e6e9ef;--hl:#f0f3f8;--good:#1a9e76;--mid:#c98a1a;--bad:#d1495b;}
    *{box-sizing:border-box}body{background:var(--bg);color:var(--ink);font:14.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 56px}
    .wrap{max-width:960px;margin:0 auto}h1{font-size:22px;margin:0 0 2px}
    .sub{color:var(--muted);margin:0 0 6px;font-size:13px}.note{color:var(--mid);font-size:12.5px;margin:0 0 16px}
    h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink2);margin:22px 0 8px}
    .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:6px 8px;overflow-x:auto}
    table{width:100%;border-collapse:collapse;font-size:13px;min-width:640px}
    th,td{padding:7px 10px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}
    th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase}
    th:nth-child(2),td:nth-child(2){text-align:left}td.sym{font-weight:650}tr:hover td{background:var(--hl)}
    .good{color:var(--good)}.mid{color:var(--mid)}.bad{color:var(--bad)}tr.dim td{color:var(--muted);text-align:center}
    .legend{color:var(--muted);font-size:12px;margin-top:12px;line-height:1.6}
    """
    secs = ""
    for name, rows in tiers:
        secs += (f'<h2>{name}</h2><div class="card"><table><thead><tr><th>#</th><th>Symbol</th>'
                 f'<th>LTP</th><th>Spread</th><th>Top bid ₹cr</th><th>5-lvl ₹cr</th>'
                 f'<th>Book ₹cr</th></tr></thead><tbody>{rowshtml(rows)}</tbody></table></div>')
    return (f'<title>Order-book depth scorecard</title><style>{css}</style>'
            f'<div class="wrap"><h1>Order-book depth — Nifty 50 &amp; Next 50</h1>'
            f'<p class="sub">Live Dhan 5-level market depth · {stamp}</p>'
            f'<p class="note">{closed_note}</p>{secs}'
            f'<div class="legend"><b>Spread</b>=(ask−bid)/mid; <span class="good">≤0.05%</span> is ~1 tick. '
            f'<b>Top bid ₹cr</b>=value resting at best bid. <b>5-lvl</b>=₹ across the 5 visible levels (both sides). '
            f'<b>Book ₹cr</b>=total pending buy+sell across the whole book × LTP. Sorted by total book depth. '
            f'Live snapshot — run 09:15–15:30 IST. Constituents approximate. Not investment advice.</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="data/depth_scorecard.html")
    args = ap.parse_args()
    print("Loading scrip master ...")
    eq, idx = load_scrip_master()
    client = DhanClient()

    tiers = []
    for name, syms in (("Nifty 50", NIFTY50), ("Nifty Next 50", sorted(set(NEXT50)))):
        try:
            rows, unresolved = run(client, syms, eq, idx)
        except DhanAPIError as e:
            print(f"{name}: API error — {str(e)[:90]}")
            rows, unresolved = [], syms
        summarize(name, rows)
        if unresolved:
            print(f"  unresolved/no-data: {', '.join(sorted(set(unresolved)))}")
        tiers.append((name, rows))

    all_rows = [r for _, rs in tiers for r in rs]
    any_live = any(not r["closed"] for r in all_rows)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = ("" if any_live else
            "⚠ Market appears CLOSED — the order book is collapsed, so depth/spread are "
            "not meaningful right now. Run during 09:15–15:30 IST.")
    Path(args.html).write_text(build_html(tiers, stamp, note))
    print(f"\n{note or 'live book captured'}\nWrote {args.html}")


if __name__ == "__main__":
    main()
