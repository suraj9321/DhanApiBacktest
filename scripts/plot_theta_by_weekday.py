"""Intraday theta decay of OTM strangles (ATM, ATM±1..±5) BY DAY OF WEEK, in the
Tuesday weekly-expiry regime (2025-08-29+). Each weekday maps to one clean
days-to-expiry (Mon=1, Tue=0, Wed=6, Thu=5, Fri=4), so the weekday IS a DTE slice.

Two figures, both weekday small-multiples with one line per width:
  1. Decay   — % of the 09:15 strangle premium remaining.
  2. Gradient — decay SPEED, % of morning premium lost per hour (−d/dt of fig 1),
                a 30-min centred slope of the averaged curve.

Each day is normalized to its own 09:15-09:20 premium, then averaged across all
days of that weekday (pinned to the weekday's modal DTE to exclude holiday shifts).
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


def load():
    con = duckdb.connect()
    offs = "(" + ",".join(str(k) for k in range(-5, 6)) + ")"
    df = con.execute(f"""
      SELECT CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) d,
             strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') tod,
             dayname(CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE)) wd,
             date_diff('day', CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE), expiry_date) dte,
             option_type, strike_offset, close
      FROM read_parquet('data/parquet/options_enriched/flag=week/*/*.parquet', hive_partitioning=true)
      WHERE NOT special_session AND expiry_date IS NOT NULL
        AND CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) >= DATE '{REGIME_START}'
        AND strike_offset IN {offs}
        AND CAST(strftime(ts AT TIME ZONE 'Asia/Kolkata','%M') AS INT) % 5 = 0
        AND strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') BETWEEN '09:15' AND '15:25'
    """).fetchdf()
    return df


def compute():
    df = load()
    # pin each weekday to its modal DTE (drop holiday-shifted days)
    df = df[df.apply(lambda r: r["wd"] in MODAL_DTE and r["dte"] == MODAL_DTE[r["wd"]], axis=1)]
    piv = df.pivot_table(index=["wd", "d", "tod"], columns=["option_type", "strike_offset"],
                         values="close", aggfunc="first")
    curves, absv, ndays = {}, {}, {}
    for wd in WEEKDAYS:
        sub = piv.loc[wd] if wd in piv.index.get_level_values(0) else None
        for k in WIDTHS:
            try:
                strg = (sub[("CE", k)] + sub[("PE", -k)]).rename("s").reset_index()
            except (KeyError, TypeError):
                continue
            # normalize each day to its 09:15-09:20 base
            per_day = []
            n = 0
            for dd, g in strg.groupby("d"):
                base = g.loc[g["tod"].between("09:15", "09:20"), "s"].mean()
                if not (base and base > 0):
                    continue
                gg = g.set_index("tod")["s"].reindex(GRID)
                per_day.append(gg / base * 100.0)
                n += 1
            if not per_day:
                continue
            mat = pd.concat(per_day, axis=1)
            curves[(wd, k)] = mat.mean(axis=1)                 # % of morning, on GRID
            absv[(wd, k)] = float(strg.loc[strg["tod"].between("09:15", "09:20"), "s"].mean())
            ndays[(wd, k)] = n
    return curves, absv, ndays


def gradient(series):
    """−d/dt over a 30-min centred window → % of morning premium lost per hour."""
    v = series.values.astype(float)
    n = len(v)
    out = np.full(n, np.nan)
    w = 3  # ±15 min
    for i in range(w, n - w):
        a, b = v[i - w], v[i + w]
        if np.isfinite(a) and np.isfinite(b):
            out[i] = -(b - a) / (2 * w * 5 / 60.0)   # %/hour, positive = decaying
    return pd.Series(out, index=series.index)


# ----------------------------- SVG panels ------------------------------------
def panel(title, dte, ndays, series_by_w, ymin, ymax, ylab, unit):
    W, H, pl, pr, pt, pb = 468, 236, 44, 12, 30, 30
    n = len(GRID)
    xs = [pl + (W - pl - pr) * i / (n - 1) for i in range(n)]
    def Y(v): return H - pb - (H - pt - pb) * (v - ymin) / (ymax - ymin)
    grid = ""
    ticks = np.linspace(ymin, ymax, 5)
    for gv in ticks:
        gy = Y(gv)
        grid += (f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{pl-6}" y="{gy+3:.1f}" text-anchor="end" class="ax">{gv:.0f}</text>')
    if ymin < 0 < ymax:
        grid += f'<line x1="{pl}" y1="{Y(0):.1f}" x2="{W-pr}" y2="{Y(0):.1f}" class="zero"/>'
    xlab = ""
    for t in ["09:15", "11:00", "13:00", "15:00", "15:25"]:
        if t in GRID:
            x = xs[GRID.index(t)]
            xlab += f'<text x="{x:.1f}" y="{H-pb+15}" text-anchor="middle" class="ax">{t}</text>'
    lines, sdata = "", {}
    for k in WIDTHS:
        s = series_by_w.get(k)
        if s is None:
            continue
        pts = " ".join(f"{xs[i]:.1f},{Y(v):.1f}" for i, v in enumerate(s.values)
                       if np.isfinite(v))
        lines += (f'<polyline points="{pts}" fill="none" stroke="{RAMP[k]}" '
                  f'stroke-width="1.9" stroke-linejoin="round"/>')
        sdata[str(k)] = [round(float(v), 2) if np.isfinite(v) else None for v in s.values]
    pdata = json.dumps({"tods": GRID, "xs": [round(x, 1) for x in xs], "series": sdata,
                        "colors": {str(k): RAMP[k] for k in WIDTHS}, "unit": unit})
    nlab = f"n≈{max(ndays.values()) if ndays else 0}"
    return (f'<div class="pane"><div class="ptitle">{title}'
            f'<span class="dte">{dte} DTE · {nlab}</span></div>'
            f'<svg viewBox="0 0 {W} {H}" width="100%" class="pane-svg">{grid}{lines}'
            f'<text transform="rotate(-90 12 {H/2:.0f})" x="12" y="{H/2:.0f}" '
            f'text-anchor="middle" class="ylab">{ylab}</text>'
            f'<g class="cross"></g>{xlab}'
            f'<script type="application/json" class="pdata">{pdata}</script></svg></div>')


def figure(curves, ndays, transform, ymin, ymax, ylab, unit, note):
    panes = ""
    for wd in WEEKDAYS:
        sbw = {k: transform(curves[(wd, k)]) for k in WIDTHS if (wd, k) in curves}
        nd = {k: ndays[(wd, k)] for k in WIDTHS if (wd, k) in ndays}
        panes += panel(wd, MODAL_DTE[wd], nd, sbw, ymin, ymax, ylab, unit)
    legend = ('<div class="pane legendpane"><div class="ptitle">Strike width</div>'
              '<div class="leg">'
              + "".join(f'<span><i class="sw" style="background:{RAMP[k]}"></i>'
                        f'{"ATM" if k==0 else f"±{k}"}</span>' for k in WIDTHS)
              + f'</div><div class="note">{note}</div></div>')
    return f'<div class="grid5">{panes}{legend}</div>'


def build(curves, ndays):
    # shared y for decay
    fig1 = figure(curves, ndays, lambda s: s, 0, 108,
                  "% of 09:15 premium", "%",
                  "Each day normalized to its 09:15 premium, averaged across the weekday’s "
                  "days (pinned to modal DTE). Tuesday-expiry regime.")
    # gradient: shared y computed from data
    grads = {key: gradient(s) for key, s in curves.items()}
    gmax = np.nanmax([np.nanmax(g.values) for g in grads.values()])
    gmin = min(0.0, np.nanmin([np.nanmin(g.values) for g in grads.values()]))
    top = float(np.ceil(gmax / 5) * 5)
    bot = float(np.floor(gmin / 5) * 5)
    fig2 = figure(curves, ndays, gradient, bot, top,
                  "%/hour lost", "%/h",
                  "Decay speed = −slope of the curve above over a 30-min window. "
                  "Higher = premium bleeding faster. Shared scale across weekdays.")

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
    .ax{fill:var(--muted);font-size:10px} .ylab{fill:var(--muted);font-size:10.5px}
    .pane-svg{overflow:visible}
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
    body = (f'<div class="wrap"><h1>Intraday theta decay by day of week — ATM &amp; ATM±1…±5 strangles</h1>'
            f'<p class="sub">Tuesday weekly-expiry regime ({REGIME_START} → 2026-08-11) · each weekday is one days-to-expiry slice · '
            f'% of the 09:15 strangle premium</p>'
            f'<h2>1 · Premium remaining (theta decay)</h2>{fig1}'
            f'<h2>2 · Decay speed (gradient)</h2>{fig2}</div>')
    return f'<title>Theta decay by weekday</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    curves, absv, ndays = compute()
    out = "data/theta_by_weekday.html"
    with open(out, "w") as f:
        f.write(build(curves, ndays))
    print("wrote", out)
    for wd in WEEKDAYS:
        row = []
        for k in WIDTHS:
            s = curves.get((wd, k))
            if s is not None:
                row.append(f"±{k}:{s.get('14:00', float('nan')):.0f}%@14:00")
        print(f"{wd:10s} DTE{MODAL_DTE[wd]}  " + "  ".join(row))


if __name__ == "__main__":
    main()
