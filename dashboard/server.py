"""
dashboard/server.py
─────────────────────────────────────────────────
Single-file Flask dashboard. Dark terminal aesthetic.
Serves live metrics from SQLite.

Run:  python dashboard/server.py
Open: http://localhost:8080
"""
import sys, os, sqlite3, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, jsonify, Response
import pandas as pd
from alpha.evaluator import evaluate_alpha_modules
from config import DB_PATH
from data.database import get_open_position_stats, get_pnl_summary

app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>POLYBOT TERMINAL</title>
<meta http-equiv="refresh" content="30">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
  :root{--g:#00ff88;--r:#ff4444;--y:#ffd700;--bg:#080808;--card:#0f0f0f;--border:#1a1a1a}
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:var(--bg);color:#ccc;font-family:'Share Tech Mono',monospace;font-size:13px;padding:20px}
  h1{color:var(--g);font-size:20px;letter-spacing:4px;margin-bottom:4px}
  .sub{color:#444;margin-bottom:24px;font-size:11px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}
  .card{background:var(--card);border:1px solid var(--border);padding:16px;border-radius:4px}
  .card .label{color:#555;font-size:10px;letter-spacing:2px;margin-bottom:6px}
  .card .val{font-size:22px;font-weight:bold}
  .pos{color:var(--g)} .neg{color:var(--r)} .neu{color:var(--y)}
  .section{background:var(--card);border:1px solid var(--border);padding:16px;border-radius:4px;margin-bottom:16px}
  .section h2{color:#555;font-size:11px;letter-spacing:3px;margin-bottom:14px}
  .chart-wrap{position:relative;height:220px}
  table{width:100%;border-collapse:collapse}
  th{color:#444;font-size:10px;letter-spacing:2px;padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)}
  td{padding:5px 8px;border-bottom:1px solid #111;font-size:12px}
  .win{color:var(--g)} .loss{color:var(--r)} .open{color:var(--y)}
  .strat-bar{display:flex;align-items:center;gap:8px;margin-bottom:8px}
  .bar-fill{height:12px;border-radius:2px;transition:width .5s}
  .bar-label{min-width:120px;color:#888;font-size:11px}
  .bar-val{color:#aaa;font-size:11px;min-width:60px;text-align:right}
  #status{position:fixed;top:12px;right:20px;font-size:10px;color:#333}
</style>
</head>
<body>
<div id="status">LIVE ● REFRESHES 30s</div>
<h1>◈ POLYBOT TERMINAL</h1>
<div class="sub">PAPER TRADING · PHASE 2 · POLYMARKET</div>

<div class="grid" id="kpis"></div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
  <div class="section">
    <h2>▸ EQUITY CURVE</h2>
    <div class="chart-wrap"><canvas id="equityChart"></canvas></div>
  </div>
  <div class="section">
    <h2>▸ CLV DISTRIBUTION</h2>
    <div class="chart-wrap"><canvas id="clvChart"></canvas></div>
  </div>
</div>

<div class="section">
  <h2>▸ STRATEGY PERFORMANCE</h2>
  <div id="stratBars"></div>
</div>

<div class="section">
  <h2>â–¸ ALPHA SHADOW</h2>
  <div id="alphaBars"></div>
</div>

<div class="section">
  <h2>▸ RECENT TRADES</h2>
  <table>
    <thead><tr>
      <th>DATE</th><th>MARKET</th><th>STRATEGY</th><th>SIDE</th>
      <th>ENTRY</th><th>SIZE $</th><th>RESULT</th><th>PNL</th><th>CLV</th>
    </tr></thead>
    <tbody id="tradesBody"></tbody>
  </table>
</div>

<div class="section">
  <h2>â–¸ RECENT ALPHA CANDIDATES</h2>
  <table>
    <thead><tr>
      <th>DATE</th><th>MARKET</th><th>ALPHA</th><th>DIR</th><th>PRED CLV</th><th>STATUS</th><th>REALIZED CLV</th>
    </tr></thead>
    <tbody id="alphaBody"></tbody>
  </table>
</div>

<script>
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const C = (sel, conf) => new Chart(document.querySelector(sel), conf);
const G = '#00ff88', R = '#ff4444', Y = '#ffd700', DIM = '#1a2a1a';
const chartDefaults = { responsive:true, maintainAspectRatio:false,
  plugins:{legend:{display:false}},
  scales:{x:{ticks:{color:'#333',font:{size:10}},grid:{color:'#111'}},
          y:{ticks:{color:'#333',font:{size:10}},grid:{color:'#111'}}} };

let equityChart, clvChart;

async function load() {
  const r = await fetch('/api/data');
  const d = await r.json();

  // KPIs
    const kpis = [
      {label:'BANKROLL',   val:'$'+d.bankroll.toFixed(2), cls: d.bankroll>=d.initial?'pos':'neg'},
      {label:'TOTAL PNL',  val:(d.pnl>=0?'+':'')+d.pnl.toFixed(2), cls:d.pnl>=0?'pos':'neg'},
      {label:'ROI',        val:d.roi.toFixed(2)+'%', cls:d.roi>=0?'pos':'neg'},
      {label:'WIN RATE',   val:d.win_rate.toFixed(1)+'%', cls:d.win_rate>50?'pos':'neg'},
      {label:'OPEN BETS',  val:d.open_bets, cls:d.open_bets < 8 ? 'neu' : 'neg'},
      {label:'AVG HOLD',   val:d.avg_hold_hours.toFixed(1)+'h', cls:d.avg_hold_hours < 6 ? 'neu' : 'neg'},
      {label:'AVG CLV',    val:d.avg_clv!=null?(d.avg_clv>0?'+':'')+d.avg_clv.toFixed(4):'N/A',
                          cls:d.avg_clv>0?'pos':d.avg_clv<0?'neg':'neu'},
      {label:'CLV EDGE',   val:d.clv_positive_rate!=null?(d.clv_positive_rate*100).toFixed(0)+'%':'N/A',
                          cls:d.clv_positive_rate>0.5?'pos':'neg'},
      {label:'ALPHA HIT',  val:d.alpha_positive_rate!=null?(d.alpha_positive_rate*100).toFixed(0)+'%':'N/A',
                          cls:d.alpha_positive_rate>0.55?'pos':'neg'},
      {label:'CLV CLOSED', val:d.clv_resolved_bets, cls:'neu'},
      {label:'ALPHA RES',  val:d.alpha_resolved_total, cls:'neu'},
      {label:'TOTAL BETS', val:d.total_bets, cls:'neu'},
      {label:'MODEL',      val:d.model_mode, cls:'neu'},
    ];
  document.getElementById('kpis').innerHTML = kpis.map(k=>
    `<div class="card"><div class="label">${k.label}</div><div class="val ${k.cls||''}">${k.val}</div></div>`
  ).join('');

  // Equity curve
  const eq = d.equity_curve;
  if (equityChart) equityChart.destroy();
  equityChart = C('#equityChart', { type:'line', data:{
    labels: eq.map(p=>p.date),
    datasets:[{data:eq.map(p=>p.bankroll), borderColor:G, backgroundColor:DIM,
               fill:true, tension:0.3, pointRadius:0}]
  }, options:{...chartDefaults}});

  // CLV distribution
  const clvBins = d.clv_bins || [];
  if (clvChart) clvChart.destroy();
  clvChart = C('#clvChart', { type:'bar', data:{
    labels: clvBins.map(b=>b.label),
    datasets:[{data:clvBins.map(b=>b.count),
               backgroundColor:clvBins.map(b=>b.label.includes('-')?R:G),
               borderWidth:0}]
  }, options:{...chartDefaults}});

  // Strategy bars
  const strats = d.strategy_stats || [];
  const maxPnl = Math.max(...strats.map(s=>Math.abs(s.pnl||0)), 1);
  document.getElementById('stratBars').innerHTML = strats.map(s=>`
    <div class="strat-bar">
      <span class="bar-label">${esc(s.strategy).toUpperCase()}</span>
      <div class="bar-fill" style="width:${Math.abs((s.pnl||0)/maxPnl)*200}px;background:${(s.pnl||0)>=0?G:R}"></div>
      <span class="bar-val">CLV ${s.avg_clv!=null?(s.avg_clv*100).toFixed(2)+'%':'N/A'}</span>
      <span class="bar-val">${s.n} bets</span>
      <span class="bar-val ${(s.active?'pos':'neg')}">${s.active?'ACTIVE':'KILLED'}</span>
    </div>`).join('');

  const alpha = d.alpha_stats || [];
  const maxAlphaClv = Math.max(...alpha.map(a=>Math.abs(a.avg_clv||0)), 0.0001);
  document.getElementById('alphaBars').innerHTML = alpha.map(a=>`
    <div class="strat-bar">
      <span class="bar-label">${esc(a.alpha_name).toUpperCase()}</span>
      <div class="bar-fill" style="width:${Math.abs((a.avg_clv||0)/maxAlphaClv)*200}px;background:${(a.avg_clv||0)>=0?G:R}"></div>
      <span class="bar-val">CLV ${a.avg_clv!=null?(a.avg_clv*100).toFixed(2)+'%':'N/A'}</span>
      <span class="bar-val">${a.n} obs</span>
      <span class="bar-val ${(a.promoted?'pos':'neu')}">${a.promoted?'PROMOTED':'SHADOW'}</span>
    </div>`).join('') || '<div class="bar-label">No alpha shadow data yet.</div>';

  // Trades
  const trades = d.recent_trades || [];
  document.getElementById('tradesBody').innerHTML = trades.map(t=>`<tr>
    <td>${(t.placed_at||'').slice(0,10)}</td>
    <td style="max-width:200px;overflow:hidden;white-space:nowrap">${esc(t.question)}</td>
    <td>${esc(t.strategy_tag)}</td>
    <td>${esc(t.side)}</td>
    <td>${(t.entry_price||0).toFixed(3)}</td>
    <td>${(t.bet_size||0).toFixed(2)}</td>
    <td class="${esc(t.result)}">${esc(t.result).toUpperCase()}</td>
    <td class="${(t.pnl||0)>=0?'win':'loss'}">${t.pnl!=null?(t.pnl>=0?'+':'')+t.pnl.toFixed(2):'—'}</td>
    <td class="${(t.clv||0)>=0?'win':'loss'}">${t.clv!=null?(t.clv*100).toFixed(2)+'%':'—'}</td>
  </tr>`).join('');

  const alphaRows = d.recent_alpha || [];
  document.getElementById('alphaBody').innerHTML = alphaRows.map(a=>`<tr>
    <td>${(a.cycle_ts||'').slice(0,10)}</td>
    <td style="max-width:200px;overflow:hidden;white-space:nowrap">${esc(a.question)}</td>
    <td>${esc(a.alpha_name)}</td>
    <td>${esc(a.direction)}</td>
    <td class="${(a.predicted_clv||0)>=0?'win':'loss'}">${a.predicted_clv!=null?(a.predicted_clv*100).toFixed(2)+'%':'â€”'}</td>
    <td class="${a.promoted?'win':'open'}">${a.promoted?'PROMOTED':'SHADOW'}</td>
    <td class="${(a.resolved_clv||0)>=0?'win':'loss'}">${a.resolved_clv!=null?(a.resolved_clv*100).toFixed(2)+'%':'â€”'}</td>
  </tr>`).join('');
}

load();
</script>
</body>
</html>"""

def _q(sql):
    try:
        with sqlite3.connect(DB_PATH, uri=isinstance(DB_PATH, str) and DB_PATH.startswith("file:")) as con:
            return pd.read_sql(sql, con)
    except Exception:
        return pd.DataFrame()

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/api/data")
def api_data():
    bets = _q("SELECT * FROM paper_bets ORDER BY placed_at DESC LIMIT 500")
    closed = bets[bets["result"] != "open"] if not bets.empty else pd.DataFrame()
    alpha_rows = _q("SELECT * FROM alpha_signals ORDER BY cycle_ts DESC LIMIT 500")
    alpha_outcomes = _q("SELECT * FROM alpha_signals WHERE resolved_clv IS NOT NULL ORDER BY cycle_ts DESC LIMIT 5000")

    bankroll_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bankroll.txt")
    try:
        bankroll = float(open(bankroll_file).read().strip())
    except Exception:
        bankroll = 1000.0

    initial = 1000.0
    try:
        from config import BANKROLL
        initial = BANKROLL
    except Exception:
        pass

    summary = get_pnl_summary()
    open_position_stats = get_open_position_stats()
    pnl       = float(closed["pnl"].sum()) if not closed.empty else 0.0
    staked    = float(closed["bet_size"].sum()) if not closed.empty else 0.0
    roi       = pnl / staked * 100 if staked > 0 else 0.0
    win_rate  = float(closed["result"].isin(["win", "timeout_win"]).mean() * 100) if not closed.empty else 0.0
    total     = len(closed)
    clv_data  = closed["clv"].dropna() if not closed.empty else pd.Series()
    avg_clv   = float(clv_data.mean()) if len(clv_data) > 0 else None
    clv_pos   = float((clv_data > 0).mean()) if len(clv_data) > 0 else None
    alpha_stats_map = evaluate_alpha_modules(alpha_outcomes)
    alpha_stats = list(alpha_stats_map.values())
    alpha_clv = alpha_outcomes["resolved_clv"].dropna() if not alpha_outcomes.empty else pd.Series(dtype=float)
    alpha_positive_rate = float((alpha_clv > 0).mean()) if len(alpha_clv) > 0 else None

    # Equity curve (last 100 trades)
    eq_bets = _q("""SELECT placed_at, pnl FROM paper_bets
                    WHERE result!='open' ORDER BY placed_at LIMIT 100""")
    equity_curve = []
    br = initial
    for _, row in eq_bets.iterrows():
        br += (row["pnl"] or 0)
        equity_curve.append({"date": str(row["placed_at"])[:10], "bankroll": round(br,2)})

    # CLV histogram
    clv_bins = []
    if len(clv_data) > 5:
        bins = [-0.10,-0.05,-0.02,-0.01,0,0.01,0.02,0.05,0.10]
        labels = ["<-10%","-10:-5%","-5:-2%","-2:-1%","-1:0%","0:1%","1:2%","2:5%",">5%"]
        counts, _ = pd.cut(clv_data, bins=bins+[1.0], labels=False, retbins=False), None
        hist, _ = pd.cut(clv_data, bins=bins+[1.0], retbins=True, include_lowest=True), None
        hist = pd.cut(clv_data, bins=bins+[1.0], labels=labels, include_lowest=True)
        for lbl in labels:
            clv_bins.append({"label": lbl, "count": int((hist==lbl).sum())})

    # Strategy stats
    strategy_stats = []
    if not closed.empty and "strategy_tag" in closed.columns:
        for strat, grp in closed.groupby("strategy_tag"):
            clv_g = grp["clv"].dropna()
            strategy_stats.append({
                "strategy": strat,
                "n": len(grp),
                "pnl": round(float(grp["pnl"].sum()), 2),
                "win_rate": round(float(grp["result"].isin(["win", "timeout_win"]).mean()*100), 1),
                "avg_clv": round(float(clv_g.mean()), 5) if len(clv_g)>0 else None,
                "resolved_clv_n": int(len(clv_g)),
                "active": True,  # killer status would need import
            })

    # Model mode
    try:
        from models.edge_model import edge_model
        model_mode = "ML" if edge_model.is_trained else "HEURISTIC"
    except Exception:
        model_mode = "?"

    recent = bets.head(20).to_dict(orient="records") if not bets.empty else []
    promoted_names = {item["alpha_name"] for item in alpha_stats if item.get("promoted")}
    recent_alpha_df = alpha_rows.head(20).copy() if not alpha_rows.empty else pd.DataFrame()
    if not recent_alpha_df.empty:
        recent_alpha_df["promoted"] = recent_alpha_df["alpha_name"].isin(promoted_names)
    recent_alpha = recent_alpha_df.to_dict(orient="records") if not recent_alpha_df.empty else []

    return jsonify({
        "bankroll":          round(bankroll, 2),
        "initial":           initial,
        "pnl":               round(pnl, 2),
        "roi":               round(roi, 2),
        "win_rate":          round(win_rate, 1),
        "total_bets":        total,
        "clv_resolved_bets": summary.get("clv_resolved_bets", 0),
        "avg_clv":           avg_clv,
        "clv_positive_rate": clv_pos,
        "alpha_positive_rate": alpha_positive_rate,
        "open_bets":         open_position_stats["n_open"],
        "avg_hold_hours":    open_position_stats["avg_hold_hours"],
        "stale_open_bets":   open_position_stats["stale_count"],
        "alpha_resolved_total": int(len(alpha_outcomes)),
        "equity_curve":      equity_curve,
        "clv_bins":          clv_bins,
        "strategy_stats":    strategy_stats,
        "alpha_stats":       alpha_stats,
        "recent_trades":     recent,
        "recent_alpha":      recent_alpha,
        "model_mode":        model_mode,
    })

if __name__ == "__main__":
    print("Dashboard: http://localhost:8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
