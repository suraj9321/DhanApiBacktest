"""Intraday ATM-straddle theta-decay curve on expiry day, averaged across all
weekly expiries (data/expiry_theta_curve.parquet). Self-contained themed HTML.

Marks the strategy's entry times (09:30/10:00/10:30) and hard close (14:55) so we
can see how much decay we capture vs leave on the table.
"""
from __future__ import annotations
import html
import json
import pandas as pd

LINE = "#3b6ea5"; POS = "#1a9e76"; NEG = "#d1495b"; AMBER = "#e0a030"; MUTE = "#8a94a6"
ENTRIES = ["09:30", "10:00", "10:30"]
CLOSE = "14:55"


def val_at(df, tod, col="pct_mean"):
    r = df[df["tod"] == tod]
    return float(r[col].iloc[0]) if len(r) else None


def build(df, title="Expiry-day theta decay — ATM straddle", instrument="straddle"):
    df = df[(df["tod"] >= "09:15") & (df["tod"] <= "15:15")].reset_index(drop=True)
    n = len(df)
    W, H, padL, padR, padT, padB = 940, 380, 52, 16, 20, 46
    xs = [padL + (W - padL - padR) * i / (n - 1) for i in range(n)]
    ymax = 106.0
    def Y(v): return H - padB - (H - padT - padB) * v / ymax
    def X(tod):
        m = df.index[df["tod"] == tod]
        return xs[m[0]] if len(m) else None

    mean = df["pct_mean"].tolist()
    p25 = df["p25"].tolist(); p75 = df["p75"].tolist()
    band = ("".join(f"{xs[i]:.1f},{Y(p75[i]):.1f} " for i in range(n))
            + "".join(f"{xs[i]:.1f},{Y(p25[i]):.1f} " for i in range(n - 1, -1, -1)))
    mline = " ".join(f"{xs[i]:.1f},{Y(mean[i]):.1f}" for i in range(n))

    grid = ""
    for gv in (0, 20, 40, 60, 80, 100):
        gy = Y(gv)
        grid += (f'<line x1="{padL}" y1="{gy:.1f}" x2="{W-padR}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{padL-8}" y="{gy+3:.1f}" text-anchor="end" class="ax">{gv}%</text>')
    xlab = ""
    for tod in ["09:15","10:00","11:00","12:00","13:00","14:00","15:00","15:15"]:
        x = X(tod)
        if x is not None:
            xlab += f'<text x="{x:.1f}" y="{H-padB+16}" text-anchor="middle" class="ax">{tod}</text>'

    marks = ""
    for e in ENTRIES:
        x = X(e); v = val_at(df, e); y = Y(v)
        marks += (f'<line x1="{x:.1f}" y1="{padT}" x2="{x:.1f}" y2="{H-padB}" stroke="{POS}" '
                  f'stroke-width="1.2" stroke-dasharray="4 4" opacity="0.7"/>'
                  f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{POS}"/>')
    xc = X(CLOSE); vc = val_at(df, CLOSE); yc = Y(vc)
    marks += (f'<line x1="{xc:.1f}" y1="{padT}" x2="{xc:.1f}" y2="{H-padB}" stroke="{NEG}" '
              f'stroke-width="1.4" stroke-dasharray="5 3"/>'
              f'<circle cx="{xc:.1f}" cy="{yc:.1f}" r="4.5" fill="{NEG}"/>'
              f'<text x="{xc-6:.1f}" y="{yc-9:.1f}" text-anchor="end" class="mk" fill="{NEG}">'
              f'close 14:55 · {vc:.0f}% left</text>')

    data = json.dumps([{"x": round(xs[i], 1), "y": round(Y(mean[i]), 1),
                        "t": df["tod"].iloc[i], "v": round(mean[i], 1),
                        "a": round(df["abs_mean"].iloc[i], 1)} for i in range(n)])
    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" class="chart">'
           f'{grid}'
           f'<polygon points="{band}" fill="{LINE}" opacity="0.13"/>'
           f'{marks}'
           f'<polyline points="{mline}" fill="none" stroke="{LINE}" stroke-width="2.4" '
           f'stroke-linejoin="round"/>'
           f'<g class="hover"></g>{xlab}'
           f'<script type="application/json" class="cdata">{data}</script></svg>')

    # stat tiles
    v0930, v1030, vclose = val_at(df, "09:30"), val_at(df, "10:30"), val_at(df, CLOSE)
    v1515 = val_at(df, "15:15"); v1400 = val_at(df, "14:00")
    abs0915 = val_at(df, "09:15", "abs_mean")
    tiles = [
        (f"Morning {instrument}", f"₹{abs0915:.0f}", "avg CE+PE premium at 09:15"),
        ("Left at our close 14:55", f"{vclose:.0f}%", "of the 09:15 premium"),
        ("Decay we capture", f"~{v1030 - vclose:.0f} pts", "10:30 entry → 14:55 close"),
        ("Left on the table", f"{vclose - v1515:.0f} pts", "14:55 → 15:15 (steepest part)"),
        ("Last-hour drop", f"{v1400 - v1515:.0f} pts", "14:00 → 15:15"),
        ("Expiries averaged", f"{int(df['n'].max())}", "all weekly expiries in data"),
    ]
    tilehtml = "".join(
        f'<div class="tile"><div class="tval">{v}</div><div class="tlab">{l}</div>'
        f'<div class="tsub">{s}</div></div>' for l, v, s in tiles)

    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;
      --grid:#e6e9ef;--border:#e6e9ef;}
    @media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;
      --ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;
      --muted:#7c8698;--grid:#232c38;--border:#232c38;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;
      --muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;}
    *{box-sizing:border-box}
    body{background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,
      "Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 56px}
    .wrap{max-width:1000px;margin:0 auto}
    h1{font-size:22px;margin:0 0 2px} .sub{color:var(--muted);margin:0 0 20px;font-size:13.5px}
    .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:16px}
    .hero{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
    @media(max-width:640px){.hero{grid-template-columns:repeat(2,1fr)}}
    .tile{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:13px 15px}
    .tval{font-size:21px;font-weight:650} .tlab{color:var(--ink2);font-size:12.5px;margin-top:2px}
    .tsub{color:var(--muted);font-size:11.5px;margin-top:1px}
    .grid{stroke:var(--grid);stroke-width:1} .ax{fill:var(--muted);font-size:11px}
    .mk{font-size:11px;font-weight:600} .chart{overflow:visible}
    .legend{display:flex;gap:18px;flex-wrap:wrap;color:var(--ink2);font-size:12.5px;margin-top:10px}
    .legend span{display:inline-flex;align-items:center;gap:6px}
    .sw{width:14px;height:3px;border-radius:2px;display:inline-block}
    .tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--border);
      border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);opacity:0;transition:opacity .08s}
    """
    js = """
    const tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
    document.querySelectorAll('svg').forEach(svg=>{
      const dn=svg.querySelector('.cdata'); if(!dn)return;
      const pts=JSON.parse(dn.textContent), g=svg.querySelector('.hover');
      const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
      dot.setAttribute('r',4.5);dot.setAttribute('fill','#3b6ea5');dot.style.opacity=0;g.appendChild(dot);
      svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();
        const sx=(e.clientX-r.left)/r.width*svg.viewBox.baseVal.width;
        let b=pts[0],bd=1e9;for(const p of pts){const d=Math.abs(p.x-sx);if(d<bd){bd=d;b=p;}}
        dot.setAttribute('cx',b.x);dot.setAttribute('cy',b.y);dot.style.opacity=1;
        tip.style.opacity=1;tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
        tip.innerHTML='<b>'+b.t+'</b><br>'+b.v+'% of morning<br>≈ ₹'+b.a+' premium';});
      svg.addEventListener('mouseleave',()=>{dot.style.opacity=0;tip.style.opacity=0;});
    });
    """
    legend = (f'<div class="legend"><span><i class="sw" style="background:{LINE}"></i>mean % of 09:15 premium</span>'
              f'<span><i class="sw" style="background:{LINE};opacity:.3"></i>25–75th percentile</span>'
              f'<span><i class="sw" style="background:{POS}"></i>entries 09:30/10:00/10:30</span>'
              f'<span><i class="sw" style="background:{NEG}"></i>hard close 14:55</span></div>')
    body = (f'<div class="wrap"><h1>{html.escape(title)}</h1>'
            f'<p class="sub">Average intraday decay across all weekly expiries · % of the 09:15 {instrument} remaining · '
            f'{int(df["n"].max())} expiries</p>'
            f'<div class="hero">{tilehtml}</div>'
            f'<div class="card">{svg}{legend}</div></div>')
    return f'<title>{html.escape(title)}</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    import sys
    parq = sys.argv[1] if len(sys.argv) > 1 else "data/expiry_theta_curve.parquet"
    title = sys.argv[2] if len(sys.argv) > 2 else "Expiry-day theta decay — ATM straddle"
    instrument = sys.argv[3] if len(sys.argv) > 3 else "straddle"
    out = sys.argv[4] if len(sys.argv) > 4 else "data/expiry_theta_curve.html"
    df = pd.read_parquet(parq)
    with open(out, "w") as f:
        f.write(build(df, title, instrument))
    print("wrote", out, "rows", len(df))


if __name__ == "__main__":
    main()
