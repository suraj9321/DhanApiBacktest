"""Reusable browser backtest report.

Reads a trades parquet (one row per trade with at least: d, side/opt, entry/exit
premiums, reason, pnl, gross, charges, slippage) and emits a self-contained,
theme-aware HTML dashboard: KPI hero, equity curve (cumulative daily P&L),
weekly & monthly P&L, and trade analytics (win/loss + ratio, exit types, streaks,
Call-day vs Put-day, extremes). All charts are inline SVG (CSP-safe); a small JS
layer adds hover tooltips. Convention per [[feedback-backtest-report]]; 1 lot per
[[feedback-one-lot-only]].

Usage:
    python scripts/backtest_report.py <trades.parquet> "<Title>" [out.html] [capital]
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date

import numpy as np
import pandas as pd

# ---- palette (diverging P&L: sign also shown by position + labels; categorical
#      Call/Put uses the CVD-safe blue/amber pair) ------------------------------
POS = "#1a9e76"      # profit green
NEG = "#d1495b"      # loss red
LINE = "#3b6ea5"     # equity line (blue)
CE_COL = "#3b6ea5"   # calls  (blue)
PE_COL = "#e0a030"   # puts   (amber)
MUTE = "#8a94a6"


def _fmt(x, dp=0):
    return f"{x:,.{dp}f}"


def load(path: str) -> pd.DataFrame:
    tr = pd.read_parquet(path)
    tr["d"] = pd.to_datetime(tr["d"])
    if "opt" not in tr.columns and "side" in tr.columns:
        tr["opt"] = np.where(tr["side"] == "bull", "PE", "CE")
    tr = tr.sort_values(["d", "entry_tod"] if "entry_tod" in tr.columns else "d").reset_index(drop=True)
    return tr


def kpis(tr, capital):
    pnl = tr["pnl"]
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    daily = tr.groupby("d")["pnl"].sum()
    eq = capital + daily.cumsum()
    peak = eq.cummax()
    maxdd = ((eq - peak) / peak).min() * 100
    dret = daily / capital
    sharpe = dret.mean() / dret.std() * np.sqrt(252) if dret.std() > 0 else float("nan")
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return {
        "net": pnl.sum(), "ret": 100 * pnl.sum() / capital, "n": len(tr),
        "win_rate": 100 * (pnl > 0).mean(),
        "n_win": int((pnl > 0).sum()), "n_loss": int((pnl <= 0).sum()),
        "avg_win": wins.mean() if len(wins) else 0, "avg_loss": losses.mean() if len(losses) else 0,
        "pf": pf, "maxdd": maxdd, "sharpe": sharpe,
        "gross": tr["gross"].sum() if "gross" in tr else float("nan"),
        "costs": (tr.get("charges", 0) + tr.get("slippage", 0)).sum(),
        "days": daily.index.nunique(),
    }


def streaks(pnl_signs):
    best = cur = 0; worst = 0; c = 0; last = 0
    for s in pnl_signs:
        if s > 0:
            c = c + 1 if last >= 0 else 1; best = max(best, c); last = 1
        else:
            c = c - 1 if last <= 0 else -1; worst = min(worst, c); last = -1
    return best, -worst


# ---------- SVG chart builders (inline, theme-aware via CSS vars) --------------
def svg_open(w, h):
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'font-family="inherit" class="chart">')


def area_line(dates, values, w=920, h=300, pad=44):
    """Equity / cumulative curve with zero baseline, hover points."""
    n = len(values)
    xs = [pad + (w - pad - 12) * i / max(n - 1, 1) for i in range(n)]
    lo, hi = min(values), max(values)
    if lo == hi:
        lo -= 1; hi += 1
    def Y(v): return h - pad - (h - 2 * pad) * (v - lo) / (hi - lo)
    ys = [Y(v) for v in values]
    zero_y = Y(0) if lo <= 0 <= hi else None
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    base = ys[0] if zero_y is None else zero_y
    area = f'{xs[0]:.1f},{base:.1f} ' + pts + f' {xs[-1]:.1f},{base:.1f}'
    grid = ""
    for frac in (0, .25, .5, .75, 1):
        gy = h - pad - (h - 2 * pad) * frac
        gv = lo + (hi - lo) * frac
        grid += (f'<line x1="{pad}" y1="{gy:.1f}" x2="{w-12}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{pad-6}" y="{gy+3:.1f}" text-anchor="end" class="ax">{_fmt(gv/1000,0)}k</text>')
    zero = (f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-12}" y2="{zero_y:.1f}" class="zero"/>'
            if zero_y is not None else "")
    # sparse x labels
    xlab = ""
    step = max(n // 6, 1)
    for i in range(0, n, step):
        xlab += (f'<text x="{xs[i]:.1f}" y="{h-pad+16}" text-anchor="middle" class="ax">'
                 f'{dates[i]}</text>')
    data = json.dumps([{"x": round(x, 1), "y": round(y, 1), "d": dates[i], "v": round(values[i])}
                       for i, (x, y) in enumerate(zip(xs, ys))])
    return (svg_open(w, h) + grid + zero +
            f'<polygon points="{area}" fill="var(--line)" opacity="0.12"/>'
            f'<polyline points="{pts}" fill="none" stroke="var(--line)" stroke-width="2" '
            f'stroke-linejoin="round"/>'
            f'<g class="eqhover"></g>{xlab}'
            f'<script type="application/json" class="eqdata">{data}</script></svg>')


def bars(labels, values, w=920, h=260, pad=44, unit="k", scale=1000):
    n = len(values)
    if n == 0:
        return "<p class='muted'>no data</p>"
    slot = (w - pad - 12) / n
    bw = min(slot * 0.7, 46)
    mx = max(abs(min(values)), abs(max(values)), 1)
    midy = pad + (h - 2 * pad) * (max(values, default=0)) / (mx * 2) if False else None
    def Y(v): return (h - pad) - (h - 2 * pad) * (v + mx) / (2 * mx)
    zero_y = Y(0)
    out = svg_open(w, h)
    out += f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{w-12}" y2="{zero_y:.1f}" class="zero"/>'
    out += (f'<text x="{pad-6}" y="{Y(mx)+3:.1f}" text-anchor="end" class="ax">+{_fmt(mx/scale,0)}{unit}</text>'
            f'<text x="{pad-6}" y="{Y(-mx)+3:.1f}" text-anchor="end" class="ax">-{_fmt(mx/scale,0)}{unit}</text>')
    step = max(n // 12, 1)
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = pad + slot * i + (slot - bw) / 2
        y = min(Y(v), zero_y); bh = abs(Y(v) - zero_y)
        col = "var(--pos)" if v >= 0 else "var(--neg)"
        out += (f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh,0.5):.1f}" '
                f'rx="3" fill="{col}" class="bar" data-lab="{html.escape(str(lab))}" '
                f'data-val="{_fmt(v,0)}"><title>{html.escape(str(lab))}: {_fmt(v,0)}</title></rect>')
        if i % step == 0:
            out += (f'<text x="{x+bw/2:.1f}" y="{h-pad+16}" text-anchor="middle" class="ax">'
                    f'{html.escape(str(lab))}</text>')
    return out + "</svg>"


def donut(n_win, n_loss, w=200, h=200):
    total = max(n_win + n_loss, 1)
    frac = n_win / total
    r, cx, cy, sw = 74, w / 2, h / 2, 26
    circ = 2 * np.pi * r
    win_len = circ * frac
    return (svg_open(w, h) +
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--neg)" stroke-width="{sw}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--pos)" stroke-width="{sw}" '
            f'stroke-dasharray="{win_len:.1f} {circ-win_len:.1f}" stroke-dashoffset="{circ*0.25:.1f}" '
            f'transform="rotate(-90 {cx} {cy})" stroke-linecap="butt"/>'
            f'<text x="{cx}" y="{cy-2}" text-anchor="middle" class="dcenter">{100*frac:.0f}%</text>'
            f'<text x="{cx}" y="{cy+18}" text-anchor="middle" class="ax">win rate</text></svg>')


def hbars(items, w=380, rowh=34, unit="", scale=1):
    """items: list of (label, value, color_css). Horizontal magnitude bars."""
    if not items:
        return "<p class='muted'>none</p>"
    mx = max(abs(v) for _, v, _ in items) or 1
    h = rowh * len(items) + 10
    out = svg_open(w, h)
    for i, (lab, v, col) in enumerate(items):
        y = 8 + i * rowh
        bw = (w - 150) * abs(v) / mx
        out += (f'<text x="0" y="{y+15}" class="hlab">{html.escape(str(lab))}</text>'
                f'<rect x="120" y="{y+3}" width="{bw:.1f}" height="16" rx="3" fill="{col}"/>'
                f'<text x="{124+bw:.1f}" y="{y+16}" class="hval">{_fmt(v/scale,0)}{unit}</text>')
    return out + "</svg>"


def build_html(tr, title, capital):
    k = kpis(tr, capital)
    daily = tr.groupby("d")["pnl"].sum().sort_index()
    cum = daily.cumsum()
    eq_dates = [d.strftime("%d %b") for d in cum.index]
    # weekly & monthly
    wk = tr.set_index("d")["pnl"].resample("W-MON").sum()
    wk = wk[wk.index >= tr["d"].min()]
    mo = tr.set_index("d")["pnl"].resample("MS").sum()
    best_streak, worst_streak = streaks(np.sign(tr["pnl"].values))
    # exits
    ex = tr["reason"].value_counts()
    ex_items = []
    ex_col = {"st_flip": "var(--line)", "eod_squareoff": MUTE, "stop_2x": "var(--neg)"}
    for r, c in ex.items():
        ex_items.append((r.replace("_", " "), int(c), ex_col.get(r, MUTE)))
    # category breakdown: CE/PE for single-leg strategies; direction for condors
    is_condor = "direction" in tr.columns and "opt" not in tr.columns
    if is_condor:
        catcol, cat_title = "direction", "By direction call"
        cat_defs = [("bullish", "Bullish days", "bull", POS),
                    ("bearish", "Bearish days", "bear", NEG),
                    ("neutral", "Neutral days", "neu", LINE)]
    else:
        catcol, cat_title = "opt", "Call-day vs Put-day"
        cat_defs = [("CE", "CALL (short CE)", "ce", CE_COL), ("PE", "PUT (short PE)", "pe", PE_COL)]

    def cat_stats(v):
        s = tr[tr[catcol] == v]["pnl"]
        return dict(n=len(s), pnl=s.sum(), win=100 * (s > 0).mean() if len(s) else 0,
                    avg=s.mean() if len(s) else 0)
    cat_data = [(lab, cls, col, cat_stats(v)) for v, lab, cls, col in cat_defs
                if cat_stats(v)["n"] > 0]
    # extremes
    best = tr.nlargest(5, "pnl")
    worst = tr.nsmallest(5, "pnl")

    def tile(label, value, sub="", tone=""):
        return (f'<div class="tile {tone}"><div class="tval">{value}</div>'
                f'<div class="tlab">{label}</div>'
                + (f'<div class="tsub">{sub}</div>' if sub else "") + '</div>')

    net_tone = "good" if k["net"] >= 0 else "bad"
    hero = "".join([
        tile("Net P&L", f'₹{_fmt(k["net"])}', f'{k["ret"]:+.2f}% on ₹{_fmt(capital/100000,1)}L', net_tone),
        tile("Win rate", f'{k["win_rate"]:.1f}%', f'{k["n_win"]}W / {k["n_loss"]}L'),
        tile("Profit factor", f'{k["pf"]:.2f}', "gross win ÷ gross loss",
             "good" if k["pf"] >= 1 else "bad"),
        tile("Max drawdown", f'{k["maxdd"]:.2f}%', "peak-to-trough", "bad"),
        tile("Sharpe", f'{k["sharpe"]:.2f}', "daily→annualised"),
        tile("Trades", f'{k["n"]}', f'over {k["days"]} days'),
        tile("Avg win / loss", f'{_fmt(k["avg_win"])} / {_fmt(k["avg_loss"])}', "₹ per trade"),
        tile("Costs", f'₹{_fmt(k["costs"])}',
             f'{100*k["costs"]/k["gross"]:.0f}% of gross' if k["gross"] else "", "bad"),
    ])

    dir_cls = {"bullish": "bull", "bearish": "bear", "neutral": "neu"}

    def trow(df):
        r = ""
        for _, x in df.iterrows():
            tone = "good" if x["pnl"] >= 0 else "bad"
            if is_condor:
                cls = dir_cls.get(x["direction"], "neu")
                mid = (f'<td><span class="pill {cls}">{x["direction"][:4]}</span></td>'
                       f'<td>{_fmt(x.get("short_put",0))} / {_fmt(x.get("short_call",0))}</td>'
                       f'<td>{x.get("entry_tod","")}→{x.get("exit_tod","")}</td>'
                       f'<td>{_fmt(x.get("credit_pts",0),1)} pt</td>')
            else:
                mid = (f'<td><span class="pill {"ce" if x["opt"]=="CE" else "pe"}">{x["opt"]}</span></td>'
                       f'<td>{_fmt(x.get("strike",0))}</td>'
                       f'<td>{x.get("entry_tod","")}→{x.get("exit_tod","")}</td>'
                       f'<td>{_fmt(x.get("entry_prem",0),1)}→{_fmt(x.get("exit_prem",0),1)}</td>')
            r += ("<tr>"
                  f'<td>{x["d"].strftime("%d %b %y")}</td>{mid}'
                  f'<td>{str(x.get("reason","")).replace("_"," ")}</td>'
                  f'<td class="{tone} num">₹{_fmt(x["pnl"])}</td></tr>')
        return r

    cvp = ('<div class="cvp" style="grid-template-columns:repeat(' + str(len(cat_data)) + ',1fr)">'
           + "".join(
               f'<div class="cvpcol"><div class="pill {cls} big">{lab}</div>'
               f'<div class="cvpnum {"good" if s["pnl"]>=0 else "bad"}">₹{_fmt(s["pnl"])}</div>'
               f'<div class="tsub">{s["n"]} · {s["win"]:.0f}% win · avg ₹{_fmt(s["avg"])}</div></div>'
               for lab, cls, col, s in cat_data)
           + '</div>'
           + hbars([(lab, s["pnl"], col) for lab, cls, col, s in cat_data], w=820, unit="", scale=1))

    period = f'{tr["d"].min().strftime("%d %b %Y")} → {tr["d"].max().strftime("%d %b %Y")}'
    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;
      --line:__LINE__;--pos:__POS__;--neg:__NEG__;--grid:#e6e9ef;--border:#e6e9ef;--zero:#b9c0cc;}
    :root[data-theme=dark],:root:not([data-theme=light]) {}
    @media (prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;
      --ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;--zero:#3a4453;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;
      --muted:#7c8698;--grid:#232c38;--border:#232c38;--zero:#3a4453;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;
      --muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;--zero:#b9c0cc;}
    *{box-sizing:border-box}
    body{background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,
      "Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 60px}
    .wrap{max-width:1000px;margin:0 auto}
    h1{font-size:22px;margin:0 0 2px} .sub{color:var(--muted);margin:0 0 22px;font-size:13.5px}
    h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink2);
      margin:30px 0 12px;font-weight:600}
    .card{background:var(--card);border:1px solid var(--border);border-radius:14px;
      padding:18px 20px;margin-bottom:16px}
    .hero{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
    @media(max-width:720px){.hero{grid-template-columns:repeat(2,1fr)}}
    .tile{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px}
    .tval{font-size:22px;font-weight:650;letter-spacing:-.01em}
    .tlab{color:var(--ink2);font-size:12.5px;margin-top:3px}
    .tsub{color:var(--muted);font-size:11.5px;margin-top:2px}
    .tile.good .tval,.good{color:var(--pos)} .tile.bad .tval,.bad{color:var(--neg)}
    .chart{overflow:visible} .grid{stroke:var(--grid);stroke-width:1}
    .zero{stroke:var(--zero);stroke-width:1.5;stroke-dasharray:3 3}
    .ax{fill:var(--muted);font-size:11px} .hlab{fill:var(--ink2);font-size:12.5px}
    .hval{fill:var(--ink);font-size:12px;font-weight:600}
    .dcenter{fill:var(--ink);font-size:30px;font-weight:700}
    .split{display:grid;grid-template-columns:220px 1fr;gap:20px;align-items:center}
    @media(max-width:720px){.split{grid-template-columns:1fr}}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
    @media(max-width:720px){.grid2{grid-template-columns:1fr}}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--border)}
    th{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase}
    td.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
    .pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;font-weight:600;color:#fff}
    .pill.ce{background:__CE__} .pill.pe{background:__PE__} .pill.big{font-size:12.5px;padding:3px 12px}
    .pill.bull{background:__POS__} .pill.bear{background:__NEG__} .pill.neu{background:__LINE__}
    .cvp{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:14px}
    .cvpcol{text-align:center} .cvpnum{font-size:26px;font-weight:700;margin:6px 0 2px}
    .streakrow{display:flex;gap:12px;flex-wrap:wrap}
    .tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--border);
      border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);
      opacity:0;transition:opacity .08s;z-index:9}
    """
    for tok, val in (("__LINE__", LINE), ("__POS__", POS), ("__NEG__", NEG),
                     ("__CE__", CE_COL), ("__PE__", PE_COL)):
        css = css.replace(tok, val)

    js = """
    const tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
    function show(t,x,y){tip.innerHTML=t;tip.style.opacity=1;tip.style.left=(x+14)+'px';tip.style.top=(y+14)+'px';}
    function hide(){tip.style.opacity=0;}
    document.querySelectorAll('.bar').forEach(b=>{
      b.addEventListener('mousemove',e=>show(b.dataset.lab+': ₹'+b.dataset.val,e.clientX,e.clientY));
      b.addEventListener('mouseleave',hide);});
    document.querySelectorAll('svg').forEach(svg=>{
      const dn=svg.querySelector('.eqdata'); if(!dn) return;
      const pts=JSON.parse(dn.textContent); const g=svg.querySelector('.eqhover');
      const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
      dot.setAttribute('r',4);dot.setAttribute('fill','var(--line)');dot.style.opacity=0;g.appendChild(dot);
      svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();
        const sx=(e.clientX-r.left)/r.width*svg.viewBox.baseVal.width;
        let best=pts[0],bd=1e9;for(const p of pts){const d=Math.abs(p.x-sx);if(d<bd){bd=d;best=p;}}
        dot.setAttribute('cx',best.x);dot.setAttribute('cy',best.y);dot.style.opacity=1;
        show('<b>'+best.d+'</b><br>cum ₹'+best.v.toLocaleString(),e.clientX,e.clientY);});
      svg.addEventListener('mouseleave',()=>{dot.style.opacity=0;hide();});
    });
    """

    parts = []
    parts.append(f'<div class="wrap"><h1>{html.escape(title)}</h1>'
                 f'<p class="sub">{period} · Tuesday weekly-expiry regime · 1 lot (75) · ₹{_fmt(capital/100000,1)}L capital</p>')
    parts.append(f'<div class="hero">{hero}</div>')
    parts.append(f'<h2>Equity curve — cumulative P&L (daily)</h2><div class="card">{area_line(eq_dates, list(cum.values))}</div>')
    parts.append('<h2>Weekly &amp; monthly P&L</h2>'
                 f'<div class="card"><div class="tsub" style="margin-bottom:6px">Weekly (₹, thousands)</div>'
                 f'{bars([d.strftime("%d %b") for d in wk.index], list(wk.values))}</div>'
                 f'<div class="card"><div class="tsub" style="margin-bottom:6px">Monthly (₹, thousands)</div>'
                 f'{bars([d.strftime("%b %y") for d in mo.index], list(mo.values))}</div>')
    parts.append('<h2>Trade analytics</h2>')
    parts.append('<div class="grid2">'
                 f'<div class="card"><div class="split"><div>{donut(k["n_win"],k["n_loss"])}</div>'
                 f'<div><div class="tval good">{k["n_win"]} wins</div>'
                 f'<div class="tval bad">{k["n_loss"]} losses</div>'
                 f'<div class="tsub">ratio {k["n_win"]}/{k["n_loss"]} = {k["n_win"]/max(k["n_loss"],1):.2f}</div>'
                 f'<div class="tsub" style="margin-top:8px">avg win ₹{_fmt(k["avg_win"])} · avg loss ₹{_fmt(k["avg_loss"])}</div>'
                 f'<div class="tsub">payoff {abs(k["avg_win"]/k["avg_loss"]) if k["avg_loss"] else 0:.2f} · PF {k["pf"]:.2f}</div>'
                 '</div></div></div>'
                 f'<div class="card"><div class="tsub" style="margin-bottom:8px">Exit types</div>'
                 f'{hbars(ex_items, w=380)}'
                 f'<div class="streakrow" style="margin-top:14px">'
                 f'{tile("Longest win streak", best_streak)}{tile("Longest loss streak", worst_streak)}</div>'
                 '</div></div>')
    parts.append(f'<h2>{cat_title}</h2><div class="card">{cvp}</div>')
    if is_condor:
        thead = ('<tr><th>Date</th><th>Dir</th><th>Short P / C</th><th>Time</th>'
                 '<th>Credit</th><th>Exit</th><th class="num">P&L</th></tr>')
    else:
        thead = ('<tr><th>Date</th><th>Opt</th><th>Strike</th><th>Time</th>'
                 '<th>Premium</th><th>Exit</th><th class="num">P&L</th></tr>')
    parts.append('<h2>Extremes</h2>'
                 '<div class="card"><div class="tsub" style="margin-bottom:6px">Top 5 winners</div>'
                 f'<table><thead>{thead}</thead><tbody>{trow(best)}</tbody></table></div>'
                 '<div class="card"><div class="tsub" style="margin-bottom:6px">Top 5 losers</div>'
                 f'<table><thead>{thead}</thead><tbody>{trow(worst)}</tbody></table></div>')
    parts.append('</div>')
    body = "\n".join(parts)
    return f'<title>{html.escape(title)}</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/backtest_pivot_supertrend_trades.parquet"
    title = sys.argv[2] if len(sys.argv) > 2 else "Pivot + Supertrend — Backtest Report"
    out = sys.argv[3] if len(sys.argv) > 3 else "data/backtest_report.html"
    capital = float(sys.argv[4]) if len(sys.argv) > 4 else 800_000.0
    tr = load(path)
    with open(out, "w") as f:
        f.write(build_html(tr, title, capital))
    print(f"Wrote {out}  ({len(tr)} trades)")


if __name__ == "__main__":
    main()
