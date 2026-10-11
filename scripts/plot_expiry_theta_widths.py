"""Expiry-day theta decay of OTM strangles at ATM±1..±5, overlaid.
Normalized % of the 09:15 premium, averaged across all weekly expiries.
Width is an ordered dimension -> sequential blue ramp (light=±1 -> dark=±5)."""
from __future__ import annotations
import html
import json
import duckdb
import numpy as np
import pandas as pd

WIDTHS = [0, 1, 2, 3, 4, 5]
RAMP = {0: "#e0952f", 1: "#9ec9e8", 2: "#6ba3d6", 3: "#3b6ea5", 4: "#2b5080", 5: "#14314f"}
POS = "#1a9e76"; NEG = "#d1495b"
ENTRIES = ["09:30", "10:00", "10:30"]; CLOSE = "14:55"
KEY_TIMES = ["09:30", "10:30", "12:00", "13:15", "14:00", "14:45", "14:55", "15:15"]


def wlabel(w):        # short (table/hover)
    return "ATM" if w == 0 else f"±{w}"


def wname(w):         # long (legend)
    return "ATM straddle" if w == 0 else f"ATM±{w} strangle"


def curve_for(con, w):
    df = con.execute(f"""
      WITH legs AS (
        SELECT ts AT TIME ZONE 'Asia/Kolkata' AS ts, option_type, close, expiry_date,
               CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) AS d,
               strftime(ts AT TIME ZONE 'Asia/Kolkata','%H:%M') AS tod
        FROM read_parquet('data/parquet/options_enriched/flag=week/*/*.parquet', hive_partitioning=true)
        WHERE NOT special_session
          AND ((option_type='CE' AND strike_offset={w}) OR (option_type='PE' AND strike_offset={-w}))
          AND CAST(ts AT TIME ZONE 'Asia/Kolkata' AS DATE) = expiry_date
      )
      SELECT d, tod, sum(CASE WHEN option_type='CE' THEN close END) ce,
                     sum(CASE WHEN option_type='PE' THEN close END) pe
      FROM legs GROUP BY d, tod ORDER BY d, tod
    """).fetchdf()
    df["s"] = df["ce"] + df["pe"]
    df = df.dropna(subset=["s"])
    df = df[(df["tod"] >= "09:15") & (df["tod"] <= "15:29")]

    def norm(g):
        base = g.loc[g["tod"].between("09:15", "09:20"), "s"].mean()
        g = g.copy(); g["pct"] = 100 * g["s"] / base if base and base > 0 else np.nan
        return g
    df = df.groupby("d", group_keys=False).apply(norm).dropna(subset=["pct"])
    df["m"] = df["tod"].str.slice(3, 5).astype(int)
    g = df[df["m"] % 5 == 0]
    summ = g.groupby("tod").agg(pct=("pct", "mean"), abs_mean=("s", "mean")).reset_index()
    return summ


def build(curves):
    tods = sorted(curves[1]["tod"])
    tods = [t for t in tods if "09:15" <= t <= "15:15"]
    n = len(tods)
    idx = {t: i for i, t in enumerate(tods)}
    W, H, padL, padR, padT, padB = 940, 400, 52, 16, 20, 46
    xs = [padL + (W - padL - padR) * i / (n - 1) for i in range(n)]
    ymax = 112.0
    def Y(v): return H - padB - (H - padT - padB) * v / ymax
    def X(t): return xs[idx[t]] if t in idx else None

    grid = ""
    for gv in (0, 20, 40, 60, 80, 100):
        gy = Y(gv)
        grid += (f'<line x1="{padL}" y1="{gy:.1f}" x2="{W-padR}" y2="{gy:.1f}" class="grid"/>'
                 f'<text x="{padL-8}" y="{gy+3:.1f}" text-anchor="end" class="ax">{gv}%</text>')
    xlab = ""
    for t in ["09:15", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "15:15"]:
        if t in idx:
            xlab += f'<text x="{X(t):.1f}" y="{H-padB+16}" text-anchor="middle" class="ax">{t}</text>'
    marks = ""
    for e in ENTRIES:
        if e in idx:
            marks += (f'<line x1="{X(e):.1f}" y1="{padT}" x2="{X(e):.1f}" y2="{H-padB}" '
                      f'stroke="{POS}" stroke-width="1.1" stroke-dasharray="4 4" opacity="0.55"/>')
    if CLOSE in idx:
        marks += (f'<line x1="{X(CLOSE):.1f}" y1="{padT}" x2="{X(CLOSE):.1f}" y2="{H-padB}" '
                  f'stroke="{NEG}" stroke-width="1.4" stroke-dasharray="5 3"/>'
                  f'<text x="{X(CLOSE)-6:.1f}" y="{padT+12}" text-anchor="end" class="mk" '
                  f'fill="{NEG}">close 14:55</text>')

    lines = ""
    series = {}
    for w in WIDTHS:
        cv = curves[w].set_index("tod")["pct"].to_dict()
        pts = " ".join(f"{xs[i]:.1f},{Y(cv.get(t, np.nan)):.1f}"
                       for i, t in enumerate(tods) if t in cv and np.isfinite(cv[t]))
        lines += (f'<polyline points="{pts}" fill="none" stroke="{RAMP[w]}" '
                  f'stroke-width="2.2" stroke-linejoin="round"/>')
        series[w] = [round(cv.get(t, float("nan")), 1) for t in tods]
    data = json.dumps({"tods": tods, "xs": [round(x, 1) for x in xs],
                       "series": {str(w): series[w] for w in WIDTHS},
                       "colors": {str(w): RAMP[w] for w in WIDTHS}})
    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%" class="chart">{grid}{marks}{lines}'
           f'<g class="cross"></g>{xlab}'
           f'<script type="application/json" class="cdata">{data}</script></svg>')

    legend = '<div class="legend">' + "".join(
        f'<span><i class="sw" style="background:{RAMP[w]}"></i>{wname(w)} '
        f'(₹{curves[w].loc[curves[w].tod=="09:15","abs_mean"].iloc[0]:.0f})</span>'
        for w in WIDTHS) + '</div>'

    # key-times table
    head = "".join(f"<th>{wlabel(w)}</th>" for w in WIDTHS)
    rows = ""
    for t in KEY_TIMES:
        cells = ""
        for w in WIDTHS:
            r = curves[w].loc[curves[w].tod == t, "pct"]
            cells += f"<td>{r.iloc[0]:.0f}%</td>" if len(r) else "<td>–</td>"
        hl = ' class="hl"' if t == CLOSE else ""
        rows += f"<tr{hl}><td>{t}</td>{cells}</tr>"
    table = (f'<table><thead><tr><th>Time</th>{head}</tr></thead><tbody>{rows}</tbody></table>')

    css = """
    :root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;--hl:#eef4fb;}
    @media(prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;--hl:#1c2836;}}
    :root[data-theme=dark]{--bg:#0f141b;--card:#161d27;--ink:#e8ecf2;--ink2:#aab4c2;--muted:#7c8698;--grid:#232c38;--border:#232c38;--hl:#1c2836;}
    :root[data-theme=light]{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--ink2:#5a6472;--muted:#8a94a6;--grid:#e6e9ef;--border:#e6e9ef;--hl:#eef4fb;}
    *{box-sizing:border-box}
    body{background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;margin:0;padding:28px 20px 56px}
    .wrap{max-width:1000px;margin:0 auto} h1{font-size:22px;margin:0 0 2px}
    .sub{color:var(--muted);margin:0 0 20px;font-size:13.5px}
    .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:16px}
    .grid{stroke:var(--grid);stroke-width:1} .ax{fill:var(--muted);font-size:11px} .mk{font-size:11px;font-weight:600} .chart{overflow:visible}
    .legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2);font-size:12.5px;margin-top:10px}
    .legend span{display:inline-flex;align-items:center;gap:6px}
    .sw{width:14px;height:3px;border-radius:2px;display:inline-block}
    table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
    th,td{text-align:right;padding:6px 10px;border-bottom:1px solid var(--border)} th:first-child,td:first-child{text-align:left}
    th{color:var(--muted);font-weight:600;font-size:11.5px} tr.hl td{background:var(--hl);font-weight:600}
    .tip{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);opacity:0;transition:opacity .08s}
    .tip b{display:block;margin-bottom:3px} .tip i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
    """
    js = """
    const tip=document.createElement('div');tip.className='tip';document.body.appendChild(tip);
    document.querySelectorAll('svg').forEach(svg=>{
      const dn=svg.querySelector('.cdata'); if(!dn)return; const D=JSON.parse(dn.textContent);
      const g=svg.querySelector('.cross'); const vb=svg.viewBox.baseVal;
      const line=document.createElementNS('http://www.w3.org/2000/svg','line');
      line.setAttribute('stroke','#8a94a6');line.setAttribute('stroke-width','1');line.setAttribute('y1',20);line.setAttribute('y2',354);line.style.opacity=0;g.appendChild(line);
      svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();
        const sx=(e.clientX-r.left)/r.width*vb.width; let bi=0,bd=1e9;
        D.xs.forEach((x,i)=>{const d=Math.abs(x-sx);if(d<bd){bd=d;bi=i;}});
        line.setAttribute('x1',D.xs[bi]);line.setAttribute('x2',D.xs[bi]);line.style.opacity=1;
        let h='<b>'+D.tods[bi]+'</b>';
        for(const w of ['0','1','2','3','4','5']){const v=D.series[w][bi];
          const lb=w==='0'?'ATM':'±'+w;
          h+='<div><i style="background:'+D.colors[w]+'"></i>'+lb+' &nbsp;'+(v==v?v+'%':'–')+'</div>';}
        tip.innerHTML=h;tip.style.opacity=1;tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';});
      svg.addEventListener('mouseleave',()=>{line.style.opacity=0;tip.style.opacity=0;});
    });
    """
    n_exp = "261"
    body = (f'<div class="wrap"><h1>Expiry-day theta decay by strike width — ATM straddle vs ATM±1 to ±5 strangles</h1>'
            f'<p class="sub">Average intraday decay across all {n_exp} weekly expiries · % of each structure’s 09:15 premium remaining · '
            f'ATM straddle (amber) holds value far longer than the OTM strangles (blue ramp)</p>'
            f'<div class="card">{svg}{legend}</div>'
            f'<div class="card"><div class="sub" style="margin:0 0 8px">% of morning premium remaining</div>{table}</div></div>')
    return f'<title>Expiry theta decay by width</title>\n<style>{css}</style>\n{body}\n<script>{js}</script>'


def main():
    con = duckdb.connect()
    curves = {w: curve_for(con, w) for w in WIDTHS}
    out = "data/expiry_theta_widths.html"
    with open(out, "w") as f:
        f.write(build(curves))
    print("wrote", out)
    for w in WIDTHS:
        c = curves[w].set_index("tod")["pct"]
        print(f"  ±{w}: 09:30={c.get('09:30',float('nan')):.0f}%  12:00={c.get('12:00',float('nan')):.0f}%  "
              f"14:00={c.get('14:00',float('nan')):.0f}%  14:55={c.get('14:55',float('nan')):.0f}%")


if __name__ == "__main__":
    main()
