"""Intraday Greeks of OTM strangles (ATM, ATM±1..±5) BY DAY OF WEEK, Tuesday
weekly-expiry regime — the Greek companion to the by-weekday theta chart. Each
weekday is one clean DTE slice (Mon=1, Tue=0, Wed=6, Thu=5, Fri=4).

Three figures, each a weekday small-multiple with one line per width:
  • Delta  — mean |net Δ| of the strangle (directional drift; net Δ≈0 at entry).
  • Gamma  — mean strangle gamma (CE+PE), ×1000; pin/breach risk, peaks 0-DTE ATM.
  • Vega   — mean strangle vega (CE+PE); IV risk, largest far from expiry.
Absolute per-unit values (not normalized), averaged across the weekday's days
(pinned to modal DTE). Shared y within each figure across weekdays.
"""
from __future__ import annotations
import html
import json
import duckdb
import numpy as np
import pandas as pd

REGIME_START = "2025-08-29"
WIDTHS = [0, 1, 2, 3, 4, 5]
RAMP = {0: "#e0952f", 1: "#9ec9e8", 2: "#6ba3d6", 3: "#3b6ea5", 4: "#2b5080", 5: "#14314f"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
MODAL_DTE = {"Monday": 1, "Tuesday": 0, "Wednesday": 6, "Thursday": 5, "Friday": 4}
GRID = [f"{9 + (15 + 5*i)//60:02d}:{(15 + 5*i) % 60:02d}" for i in range((15*60 + 25 - (9*60+15))//5 + 1)]
GRID = [t for t in GRID if "09:15" <= t <= "15:25"]

# (key, label, ylabel, unit, scale, agg) — agg maps (dce,dpe,gce,gpe,vce,vpe)->value
METRICS = [
    ("delta", "Delta", "mean |net Δ|", "", 1.0, lambda dce, dpe, gce, gpe, vce, vpe: abs(dce + dpe)),
    ("gamma", "Gamma", "gamma ×10³", "", 1000.0, lambda dce, dpe, gce, gpe, vce, vpe: gce + gpe),
    ("vega", "Vega", "vega (pts/vol)", "", 1.0, lambda dce, dpe, gce, gpe, vce, vpe: vce + vpe),
]


def load():
    con = duckdb.connect()
    offs = "(" + ",".join(str(k) for k in range(-5, 6)) + ")"
    return con.execute(f"""
      SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) d,
             strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') tod,
             dayname(CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE)) wd,
             date_diff('day', CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE), expiry_date) dte,
             option_type, strike_offset, delta, gamma, vega
      FROM read_parquet('data/parquet/options_enriched/flag=week/*/*.parquet', hive_partitioning=true)
      WHERE NOT special_session AND expiry_date IS NOT NULL
        AND CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) >= DATE '{REGIME_START}'
        AND strike_offset IN {offs}
        AND CAST(strftime(ts AT TIME ZONE 'Asia/Kolkata','%M') AS INT) % 5 = 0
        AND strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') BETWEEN '09:15' AND '15:25'
    """).fetchdf()


def compute():
    df = load()
    df = df[df.apply(lambda r: r["wd"] in MODAL_DTE and r["dte"] == MODAL_DTE[r["wd"]], axis=1)]
    piv = df.pivot_table(index=["wd", "d", "tod"], columns=["option_type", "strike_offset"],
                         values=["delta", "gamma", "vega"], aggfunc="first")
    out = {m[0]: {} for m in METRICS}
    ndays = {}
    for wd in WEEKDAYS:
        if wd not in piv.index.get_level_values(0):
            continue
        sub = piv.loc[wd]
        for k in WIDTHS:
            try:
                dce, dpe = sub[("delta", "CE", k)], sub[("delta", "PE", -k)]
                gce, gpe = sub[("gamma", "CE", k)], sub[("gamma", "PE", -k)]
                vce, vpe = sub[("vega", "CE", k)], sub[("vega", "PE", -k)]
            except KeyError:
                continue
            frame = pd.DataFrame({"dce": dce, "dpe": dpe, "gce": gce, "gpe": gpe,
                                  "vce": vce, "vpe": vpe}).dropna()
            if frame.empty:
                continue
            frame = frame.reset_index()  # cols: d, tod, ...
            for key, _, _, _, scale, agg in METRICS:
                frame["_v"] = agg(frame.dce, frame.dpe, frame.gce, frame.gpe,
                                  frame.vce, frame.vpe) * scale
                curve = frame.groupby("tod")["_v"].mean().reindex(GRID)
                out[key][(wd, k)] = curve
            ndays[(wd, k)] = frame["d"].nunique()
    return out, ndays


def panel(title, sub, ndays, series_by_w, ymin, ymax, ylab, unit):
    W, H, pl, pr, pt, pb = 468, 236, 48, 12, 30, 30
    n = len(GRID)
    xs = [pl + (W - pl - pr) * i / (n - 1) for i in range(n)]
    def Y(v): return H - pb - (H - pt - pb) * (v - ymin) / (ymax - ymin)
    grid = ""
    for gv in np.linspace(ymin, ymax, 5):
        gy = Y(gv)
        lbl = f"{gv:.2f}" if ymax < 5 else f"{gv:.0f}"
        grid += (f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{pl-6}" y="{gy+3:.1f}" text-anchor="end" class="ax">{lbl}</text>')
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
        sdata[str(k)] = [round(float(v), 3) if np.isfinite(v) else None for v in s.values]
    pdata = json.dumps({"tods": GRID, "xs": [round(x, 1) for x in xs], "series": sdata,
                        "colors": {str(k): RAMP[k] for k in WIDTHS}, "unit": unit})
    nlab = f"n≈{max(ndays.values()) if ndays else 0}"
    return (f'<div class="pane"><div class="ptitle">{title}'
            f'<span class="dte">{sub} DTE · {nlab}</span></div>'
            f'<svg viewBox="0 0 {W} {H}" width="100%" class="pane-svg">{grid}{lines}'
            f'<text transform="rotate(-90 13 {H/2:.0f})" x="13" y="{H/2:.0f}" text-anchor="middle" class="ylab">{ylab}</text>'
            f'<g class="cross"></g>{xlab}'
            f'<script type="application/json" class="pdata">{pdata}</script></svg></div>')


def figure(metric_curves, ndays, ylab, unit, note):
    vals = [v for s in metric_curves.values() for v in s.values if np.isfinite(v)]
    ymax = float(np.nanpercentile(vals, 99.5)) * 1.05 if vals else 1.0
    ymax = ymax if ymax > 0 else 1.0
    panes = ""
    for wd in WEEKDAYS:
        sbw = {k: metric_curves[(wd, k)] for k in WIDTHS if (wd, k) in metric_curves}
        nd = {k: ndays[(wd, k)] for k in WIDTHS if (wd, k) in ndays}
        panes += panel(wd, MODAL_DTE[wd], nd, sbw, 0, ymax, ylab, unit)
    legend = ('<div class="pane legendpane"><div class="ptitle">Strike width</div><div class="leg">'
              + "".join(f'<span><i class="sw" style="background:{RAMP[k]}"></i>{"ATM" if k==0 else f"±{k}"}</span>'
                        for k in WIDTHS)
              + f'</div><div class="note">{note}</div></div>')
    return f'<div class="grid5">{panes}{legend}</div>'


def build(metrics, ndays):
    secs = ""
    notes = {
        "delta": "Net Δ of a symmetric strangle ≈ 0 at entry, so this is mean |net Δ| — "
                 "directional exposure that drifts intraday (gamma-driven, largest on 0-DTE).",
        "gamma": "Strangle gamma (CE+PE), ×1000. Pin/breach risk — small far from expiry, "
                 "explodes near the money on expiry day.",
        "vega": "Strangle vega (CE+PE), points per vol-point. IV sensitivity — largest far "
                "from expiry, tiny on expiry day.",
    }
    titles = {"delta": "1 · Delta (directional drift)", "gamma": "2 · Gamma (pin/breach risk)",
              "vega": "3 · Vega (IV risk)"}
    for key, lab, ylab, unit, scale, agg in METRICS:
        secs += f'<h2>{titles[key]}</h2>' + figure(metrics[key], ndays, ylab, unit, notes[key])
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
    .grid{stroke:var(--grid);stroke-width:1}
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
          h+='<div><i style="background:'+D.colors[k]+'"></i>'+lb+' &nbsp;'+(v==null?'–':v)+'</div>';}
        tip.innerHTML=h;tip.style.opacity=1;tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';});
      svg.addEventListener('mouseleave',()=>{ln.style.opacity=0;tip.style.opacity=0;});
    });
    """
    body = (f'<div class="wrap"><h1>Intraday Greeks by day of week — ATM &amp; ATM±1…±5 strangles</h1>'
            f'<p class="sub">Tuesday weekly-expiry regime ({REGIME_START} → 2026-08-11) · each weekday is one days-to-expiry slice · '
            f'per-unit values, averaged</p>{secs}</div>')
    return f'<title>Strangle Greeks by weekday</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    metrics, ndays = compute()
    out = "data/greeks_by_weekday.html"
    with open(out, "w") as f:
        f.write(build(metrics, ndays))
    print("wrote", out)
    for key, lab, *_ in METRICS:
        print(f"\n{lab} @ 14:00:")
        for wd in WEEKDAYS:
            row = [f"±{k}:{metrics[key][(wd,k)].get('14:00', float('nan')):.3f}"
                   for k in WIDTHS if (wd, k) in metrics[key]]
            print(f"  {wd:10s} DTE{MODAL_DTE[wd]}  " + "  ".join(row))


if __name__ == "__main__":
    main()
