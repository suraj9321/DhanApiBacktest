"""Intraday theta decay of Nifty MONTHLY OTM strangles (ATM, ATM±1..±5) BY
TIME-TO-EXPIRY — the faithful monthly analogue of the weekly by-weekday chart.

For the monthly, a calendar weekday spans the whole 0..31 DTE cycle, so weekday
carries no information; the meaningful slice is days-to-expiry. Decay-by-DTE is
regime-invariant (independent of whether expiry falls on Thu or Tue), so this
uses the FULL monthly history for a robust sample.

Two figures, both DTE-bucket small-multiples with one line per width:
  1. Decay    — % of the 09:15 strangle premium remaining.
  2. Gradient — decay speed, % of morning premium lost per hour (30-min centred slope).
Each day normalized to its own 09:15-09:20 premium, averaged across the bucket's days.
"""
from __future__ import annotations
import html
import json
import duckdb
import numpy as np
import pandas as pd

WIDTHS = [0, 1, 2, 3, 4, 5]
RAMP = {0: "#e0952f", 1: "#9ec9e8", 2: "#6ba3d6", 3: "#3b6ea5", 4: "#2b5080", 5: "#14314f"}
# (label, predicate on calendar DTE) — near-expiry emphasis
BUCKETS = [
    ("Expiry day", "0 DTE", lambda x: x == 0),
    ("1–2 DTE", "final run-up", lambda x: 1 <= x <= 2),
    ("3–6 DTE", "expiry week", lambda x: 3 <= x <= 6),
    ("7–14 DTE", "~2nd week out", lambda x: 7 <= x <= 14),
    ("15+ DTE", "start of cycle", lambda x: x >= 15),
]
GRID = [f"{9 + (15 + 5*i)//60:02d}:{(15 + 5*i) % 60:02d}" for i in range((15*60 + 25 - (9*60+15))//5 + 1)]
GRID = [t for t in GRID if "09:15" <= t <= "15:25"]


def load():
    con = duckdb.connect()
    offs = "(" + ",".join(str(k) for k in range(-5, 6)) + ")"
    return con.execute(f"""
      SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) d,
             strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') tod,
             date_diff('day', CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE), expiry_date) dte,
             option_type, strike_offset, close
      FROM read_parquet('data/parquet/options_enriched/flag=month/*/*.parquet', hive_partitioning=true)
      WHERE NOT special_session AND expiry_date IS NOT NULL
        AND strike_offset IN {offs}
        AND CAST(strftime(ts AT TIME ZONE 'Asia/Kolkata','%M') AS INT) % 5 = 0
        AND strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') BETWEEN '09:15' AND '15:25'
    """).fetchdf()


def compute():
    df = load()
    dte_by_day = df.drop_duplicates("d").set_index("d")["dte"].to_dict()
    piv = df.pivot_table(index=["d", "tod"], columns=["option_type", "strike_offset"],
                         values="close", aggfunc="first")
    curves, ndays = {}, {}
    for blab, _, pred in BUCKETS:
        days = [d for d, x in dte_by_day.items() if pred(x)]
        sub = piv.loc[piv.index.get_level_values(0).isin(days)]
        for k in WIDTHS:
            try:
                strg = (sub[("CE", k)] + sub[("PE", -k)]).rename("s").reset_index()
            except (KeyError, TypeError):
                continue
            per_day, n = [], 0
            for dd, g in strg.groupby("d"):
                base = g.loc[g["tod"].between("09:15", "09:20"), "s"].mean()
                if not (base and base > 0):
                    continue
                per_day.append(g.set_index("tod")["s"].reindex(GRID) / base * 100.0)
                n += 1
            if per_day:
                curves[(blab, k)] = pd.concat(per_day, axis=1).mean(axis=1)
                ndays[(blab, k)] = n
    return curves, ndays


def gradient(series):
    v = series.values.astype(float); n = len(v)
    out = np.full(n, np.nan); w = 3
    for i in range(w, n - w):
        a, b = v[i - w], v[i + w]
        if np.isfinite(a) and np.isfinite(b):
            out[i] = -(b - a) / (2 * w * 5 / 60.0)
    return pd.Series(out, index=series.index)


def panel(title, sub, ndays, series_by_w, ymin, ymax, ylab, unit):
    W, H, pl, pr, pt, pb = 468, 236, 44, 12, 30, 30
    n = len(GRID)
    xs = [pl + (W - pl - pr) * i / (n - 1) for i in range(n)]
    def Y(v): return H - pb - (H - pt - pb) * (v - ymin) / (ymax - ymin)
    grid = ""
    for gv in np.linspace(ymin, ymax, 5):
        gy = Y(gv)
        grid += (f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{pl-6}" y="{gy+3:.1f}" text-anchor="end" class="ax">{gv:.0f}</text>')
    if ymin < 0 < ymax:
        grid += f'<line x1="{pl}" y1="{Y(0):.1f}" x2="{W-pr}" y2="{Y(0):.1f}" class="zero"/>'
    xlab = ""
    for t in ["09:15", "11:00", "13:00", "15:00", "15:25"]:
        if t in GRID:
            xlab += f'<text x="{xs[GRID.index(t)]:.1f}" y="{H-pb+15}" text-anchor="middle" class="ax">{t}</text>'
    lines, sdata = "", {}
    for k in WIDTHS:
        s = series_by_w.get(k)
        if s is None:
            continue
        pts = " ".join(f"{xs[i]:.1f},{Y(v):.1f}" for i, v in enumerate(s.values) if np.isfinite(v))
        lines += f'<polyline points="{pts}" fill="none" stroke="{RAMP[k]}" stroke-width="1.9" stroke-linejoin="round"/>'
        sdata[str(k)] = [round(float(v), 2) if np.isfinite(v) else None for v in s.values]
    pdata = json.dumps({"tods": GRID, "xs": [round(x, 1) for x in xs], "series": sdata,
                        "colors": {str(k): RAMP[k] for k in WIDTHS}, "unit": unit})
    nlab = f"n≈{max(ndays.values()) if ndays else 0}"
    return (f'<div class="pane"><div class="ptitle">{title}'
            f'<span class="dte">{sub} · {nlab}</span></div>'
            f'<svg viewBox="0 0 {W} {H}" width="100%" class="pane-svg">{grid}{lines}'
            f'<text transform="rotate(-90 12 {H/2:.0f})" x="12" y="{H/2:.0f}" text-anchor="middle" class="ylab">{ylab}</text>'
            f'<g class="cross"></g>{xlab}'
            f'<script type="application/json" class="pdata">{pdata}</script></svg></div>')


def figure(curves, ndays, transform, ymin, ymax, ylab, unit, note):
    panes = ""
    for blab, sub, _ in BUCKETS:
        sbw = {k: transform(curves[(blab, k)]) for k in WIDTHS if (blab, k) in curves}
        nd = {k: ndays[(blab, k)] for k in WIDTHS if (blab, k) in ndays}
        panes += panel(blab, sub, nd, sbw, ymin, ymax, ylab, unit)
    legend = ('<div class="pane legendpane"><div class="ptitle">Strike width</div><div class="leg">'
              + "".join(f'<span><i class="sw" style="background:{RAMP[k]}"></i>{"ATM" if k==0 else f"±{k}"}</span>'
                        for k in WIDTHS)
              + f'</div><div class="note">{note}</div></div>')
    return f'<div class="grid5">{panes}{legend}</div>'


def build(curves, ndays):
    fig1 = figure(curves, ndays, lambda s: s, 0, 108, "% of 09:15 premium", "%",
                  "Each day normalized to its 09:15 premium, averaged across the bucket’s days. "
                  "Nifty monthly, full history — decay-by-DTE is regime-invariant.")
    grads = {key: gradient(s) for key, s in curves.items()}
    gmax = np.nanmax([np.nanmax(g.values) for g in grads.values()])
    gmin = min(0.0, np.nanmin([np.nanmin(g.values) for g in grads.values()]))
    fig2 = figure(curves, ndays, gradient, float(np.floor(gmin/5)*5), float(np.ceil(gmax/5)*5),
                  "%/hour lost", "%/h",
                  "Decay speed = −slope of the curve above over a 30-min window. "
                  "Shared scale — expiry-day decay dwarfs the rest.")
    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;--zero:#b9c0cc;}
    @media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;--zero:#3a4453;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;--zero:#3a4453;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;--zero:#b9c0cc;}
    *{box-sizing:border-box}
    body{background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 56px}
    .wrap{max-width:1000px;margin:0 auto} h1{font-size:22px;margin:0 0 2px}
    h2{font-size:15px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink2);margin:26px 0 12px;font-weight:600}
    .sub{color:var(--muted);margin:0 0 14px;font-size:13.5px}
    .grid5{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media(max-width:680px){.grid5{grid-template-columns:1fr}}
    .pane{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:10px 12px 6px}
    .ptitle{font-size:13px;font-weight:650;display:flex;justify-content:space-between;align-items:baseline}
    .dte{font-size:11px;font-weight:500;color:var(--muted)}
    .grid{stroke:var(--grid);stroke-width:1} .zero{stroke:var(--zero);stroke-width:1.2;stroke-dasharray:3 3}
    .ax{fill:var(--muted);font-size:10px} .ylab{fill:var(--muted);font-size:10.5px} .pane-svg{overflow:visible}
    .legendpane{display:flex;flex-direction:column;justify-content:center}
    .leg{display:flex;flex-wrap:wrap;gap:10px 16px;margin:10px 0 8px}
    .leg span{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink2)}
    .sw{width:15px;height:3px;border-radius:2px;display:inline-block}
    .note{font-size:11.5px;color:var(--muted);line-height:1.45}
    .tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);opacity:0;transition:opacity .08s}
    .tip b{display:block;margin-bottom:3px} .tip i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
    """
    js = """
    const tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
    document.querySelectorAll('svg.pane-svg').forEach(svg=>{
      const dn=svg.querySelector('.pdata'); if(!dn)return; const D=JSON.parse(dn.textContent);
      const g=svg.querySelector('.cross'), vb=svg.viewBox.baseVal;
      const ln=document.createElementNS('http://www.w3.org/2000/svg','line');
      ln.setAttribute('stroke','#8a94a6');ln.setAttribute('stroke-width','1');ln.setAttribute('y1',30);ln.setAttribute('y2',206);ln.style.opacity=0;g.appendChild(ln);
      svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();
        const sx=(e.clientX-r.left)/r.width*vb.width; let bi=0,bd=1e9;
        D.xs.forEach((x,i)=>{const d=Math.abs(x-sx);if(d<bd){bd=d;bi=i;}});
        ln.setAttribute('x1',D.xs[bi]);ln.setAttribute('x2',D.xs[bi]);ln.style.opacity=1;
        let h='<b>'+D.tods[bi]+'</b>';
        for(const k of ['0','1','2','3','4','5']){const s=D.series[k]; if(!s)continue; const v=s[bi];
          const lb=k==='0'?'ATM':'±'+k;
          h+='<div><i style="background:'+D.colors[k]+'"></i>'+lb+' &nbsp;'+(v==null?'–':v+D.unit)+'</div>';}
        tip.innerHTML=h;tip.style.opacity=1;tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';});
      svg.addEventListener('mouseleave',()=>{ln.style.opacity=0;tip.style.opacity=0;});
    });
    """
    body = (f'<div class="wrap"><h1>Nifty MONTHLY intraday theta decay by time-to-expiry — ATM &amp; ATM±1…±5</h1>'
            f'<p class="sub">Full monthly history (2021–2026) · sliced by days-to-expiry (weekday carries no info for monthly) · '
            f'% of the 09:15 strangle premium</p>'
            f'<h2>1 · Premium remaining (theta decay)</h2>{fig1}'
            f'<h2>2 · Decay speed (gradient)</h2>{fig2}</div>')
    return f'<title>Monthly theta decay by DTE</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    curves, ndays = compute()
    out = "data/theta_monthly_dte.html"
    with open(out, "w") as f:
        f.write(build(curves, ndays))
    print("wrote", out)
    for blab, sub, _ in BUCKETS:
        row = [f"±{k}:{curves[(blab,k)].get('14:00', float('nan')):.0f}%" for k in WIDTHS if (blab, k) in curves]
        print(f"{blab:11s} ({sub:14s})  @14:00  " + "  ".join(row))


if __name__ == "__main__":
    main()
