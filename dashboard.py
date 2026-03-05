#!/usr/bin/env python3
"""
Acer Aspire 5 — Dashboard de Análise
Gera um relatório HTML a partir do banco de dados.

Uso:
    python dashboard.py
    python dashboard.py --db C:\outro\caminho\monitor.db
    python dashboard.py --db monitor.db --output relatorio.html --no-open
    python dashboard.py --window 10
"""

import sqlite3
import json
import sys
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent


# ── Args ──────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Acer Crash Monitor — Dashboard")
    parser.add_argument("--db", type=Path, default=BASE_DIR / "monitor.db",
                        help="Caminho para o banco de dados (padrão: monitor.db)")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "dashboard.html",
                        help="Caminho do HTML gerado (padrão: dashboard.html)")
    parser.add_argument("--no-open", action="store_true",
                        help="Não abre o navegador automaticamente")
    parser.add_argument("--window", type=int, default=5, metavar="MINUTOS",
                        help="Janela de análise pré-crash em minutos (padrão: 5)")
    return parser.parse_args()


# ── load_data ─────────────────────────────────────────────────
def load_data(db_path):
    """Carrega dados brutos do banco SQLite."""
    if not db_path.exists():
        print(f"Banco não encontrado: {db_path}")
        print("Rode primeiro: python monitor.py")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    snapshots = conn.execute("""
        SELECT ts, cpu_pct, cpu_temp, ram_pct, swap_pct,
               battery_pct, battery_plugged, proc_count, gpu_temp
        FROM snapshots ORDER BY ts DESC LIMIT 2000
    """).fetchall()

    boots = conn.execute(
        "SELECT * FROM boot_events ORDER BY ts DESC"
    ).fetchall()

    alerts = conn.execute(
        "SELECT * FROM alerts ORDER BY ts DESC LIMIT 100"
    ).fetchall()

    stats = conn.execute("""
        SELECT COUNT(*) as total_snaps,
               AVG(cpu_pct) as avg_cpu,
               MAX(cpu_temp) as max_temp,
               AVG(cpu_temp) as avg_temp,
               MAX(ram_pct) as max_ram,
               AVG(ram_pct) as avg_ram,
               MIN(ts) as first_ts,
               MAX(ts) as last_ts
        FROM snapshots
    """).fetchone()

    conn.close()
    return snapshots, boots, alerts, stats


# ── process_data ──────────────────────────────────────────────
def process_data(snapshots, boots, alerts, stats, db_path, window_minutes):
    """Transforma dados brutos em estruturas prontas para renderização."""
    snaps_asc = list(reversed(snapshots))

    # Séries para gráficos
    charts = {
        "labels":   [s["ts"][11:19] for s in snaps_asc],
        "cpu":      [round(s["cpu_pct"]      or 0, 1) for s in snaps_asc],
        "temp":     [round(s["cpu_temp"]     or 0, 1) for s in snaps_asc],
        "ram":      [round(s["ram_pct"]      or 0, 1) for s in snaps_asc],
        "battery":  [round(s["battery_pct"]  or 0, 1) for s in snaps_asc],
    }

    # Resumo geral
    monitoring_hours = 0
    if stats and stats["first_ts"] and stats["last_ts"]:
        t1 = datetime.fromisoformat(stats["first_ts"])
        t2 = datetime.fromisoformat(stats["last_ts"])
        monitoring_hours = (t2 - t1).total_seconds() / 3600

    summary = {
        "total_snaps":       stats["total_snaps"] if stats else 0,
        "monitoring_hours":  monitoring_hours,
        "crash_count":       sum(1 for b in boots if b["kind"] == "crash"),
        "max_temp":          stats["max_temp"] or 0 if stats else 0,
        "avg_temp":          stats["avg_temp"] or 0 if stats else 0,
        "avg_cpu":           stats["avg_cpu"]  or 0 if stats else 0,
        "max_ram":           stats["max_ram"]  or 0 if stats else 0,
        "avg_ram":           stats["avg_ram"]  or 0 if stats else 0,
        "generated_at":      datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    }

    # Análise pré-crash
    analysis = _build_analysis(db_path, window_minutes)

    return charts, summary, analysis


def _build_analysis(db_path, window_minutes):
    """Gera análise dos minutos antes de cada reboot (lógica de analyze.py)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    boots = conn.execute("""
        SELECT * FROM boot_events
        WHERE notes != 'Primeira execução'
        ORDER BY ts
    """).fetchall()

    if not boots:
        conn.close()
        return []

    results = []
    for boot in boots:
        last_snap = boot["last_snap_ts"]
        if not last_snap:
            continue

        window_start = (
            datetime.fromisoformat(last_snap) - timedelta(minutes=window_minutes)
        ).isoformat()

        snaps = conn.execute("""
            SELECT * FROM snapshots
            WHERE ts BETWEEN ? AND ? ORDER BY ts
        """, (window_start, last_snap)).fetchall()

        if not snaps:
            continue

        cpu_vals  = [s["cpu_pct"]      for s in snaps if s["cpu_pct"]]
        temp_vals = [s["cpu_temp"]     for s in snaps if s["cpu_temp"]]
        ram_vals  = [s["ram_pct"]      for s in snaps if s["ram_pct"]]
        bat_vals  = [s["battery_pct"]  for s in snaps if s["battery_pct"] is not None]

        cpu_max  = max(cpu_vals)   if cpu_vals  else None
        temp_max = max(temp_vals)  if temp_vals else None
        ram_avg  = sum(ram_vals) / len(ram_vals) if ram_vals else None
        bat_last = bat_vals[-1]    if bat_vals  else None
        plugged  = snaps[-1]["battery_plugged"]

        risks = []
        if temp_max and temp_max > 85:
            risks.append(f"🌡️ SUPERAQUECIMENTO ({temp_max:.0f}°C)")
        if cpu_max and cpu_max > 90:
            risks.append(f"⚙️ CPU SATURADA ({cpu_max:.0f}%)")
        if ram_avg and ram_avg > 85:
            risks.append(f"🧠 RAM ALTA ({ram_avg:.0f}%)")
        if bat_last is not None and bat_last < 5 and not plugged:
            risks.append(f"🔋 BATERIA CRÍTICA ({bat_last:.0f}%)")

        results.append({
            "boot_ts":   boot["ts"][:19],
            "kind":      boot["kind"] or "desconhecido",
            "n_snaps":   len(snaps),
            "cpu_avg":   sum(cpu_vals) / len(cpu_vals) if cpu_vals else None,
            "cpu_max":   cpu_max,
            "temp_avg":  sum(temp_vals) / len(temp_vals) if temp_vals else None,
            "temp_max":  temp_max,
            "ram_avg":   ram_avg,
            "bat_last":  bat_last,
            "plugged":   plugged,
            "risks":     risks,
        })

    conn.close()
    return results


# ── render_html ───────────────────────────────────────────────
def _render_boot_rows(boots):
    if not boots:
        return ""
    rows = ""
    for b in boots:
        kind = b["kind"] if b["kind"] else "desconhecido"
        if kind == "crash":
            badge = '<span class="badge danger">💥 CRASH</span>'
        elif kind == "intencional":
            badge = '<span class="badge ok">✋ Intencional</span>'
        elif b["notes"] == "Primeira execução":
            badge = '<span class="badge ok">▶ Início</span>'
        else:
            badge = '<span class="badge warn">❓ Desconhecido</span>'
        rows += f"""
        <tr>
            <td>{b['ts'][:19]}</td>
            <td>{badge}</td>
            <td>{b['boot_time'][:19] if b['boot_time'] else '—'}</td>
            <td class="mono small">{b['last_snap_ts'][:19] if b['last_snap_ts'] else '—'}</td>
        </tr>"""
    return rows


def _render_alert_rows(alerts):
    if not alerts:
        return ""
    rows = ""
    for a in alerts:
        color = "danger" if a["kind"] == "temp" and a["value"] > 85 else "warn"
        rows += f"""
        <tr>
            <td>{a['ts'][:19]}</td>
            <td><span class="badge {color}">{a['kind'].upper()}</span></td>
            <td>{a['value']:.1f}</td>
            <td>{a['message']}</td>
        </tr>"""
    return rows


def _render_analysis_rows(analysis):
    if not analysis:
        return "<p class='empty'>Nenhuma reinicialização registrada ainda.</p>"

    rows = ""
    for r in analysis:
        kind = r["kind"]
        if kind == "crash":
            badge = '<span class="badge danger">💥 CRASH</span>'
        elif kind == "intencional":
            badge = '<span class="badge ok">✋ Intencional</span>'
        else:
            badge = '<span class="badge warn">❓ Desconhecido</span>'

        risks_html = "".join(f'<div class="risk-item">{risk}</div>' for risk in r["risks"]) \
                     if r["risks"] else '<span class="muted">Sem indicadores óbvios</span>'

        plugged_str = "tomada" if r["plugged"] else "bateria"
        bat_str = f"{r['bat_last']:.0f}% ({plugged_str})" if r["bat_last"] is not None else "—"

        rows += f"""
        <tr>
            <td>{r['boot_ts']}</td>
            <td>{badge}</td>
            <td class="mono">{r['temp_avg']:.1f}° / {r['temp_max']:.1f}°</td>
            <td class="mono">{r['cpu_avg']:.1f}% / {r['cpu_max']:.1f}%</td>
            <td class="mono">{r['ram_avg']:.1f}%</td>
            <td class="mono">{bat_str}</td>
            <td>{risks_html}</td>
        </tr>""" if (r['temp_avg'] and r['cpu_avg'] and r['ram_avg']) else f"""
        <tr>
            <td>{r['boot_ts']}</td>
            <td>{badge}</td>
            <td colspan="4" class="muted mono">Dados insuficientes nessa janela</td>
            <td>{risks_html}</td>
        </tr>"""

    return f"""
    <table>
        <thead><tr>
            <th>Quando</th><th>Tipo</th>
            <th>Temp avg/max</th><th>CPU avg/max</th>
            <th>RAM avg</th><th>Bateria</th><th>Indicadores</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


def render_html(charts, summary, boots, alerts, analysis):
    """Monta o HTML final a partir dos dados processados."""

    boot_rows   = _render_boot_rows(boots)
    alert_rows  = _render_alert_rows(alerts)
    analysis_html = _render_analysis_rows(analysis)

    boots_table   = f"<table><thead><tr><th>Quando</th><th>Tipo</th><th>Boot em</th><th>Último snap</th></tr></thead><tbody>{boot_rows}</tbody></table>" \
                    if boot_rows else "<p class='empty'>Nenhuma reinicialização registrada ainda.</p>"
    alerts_table  = f"<table><thead><tr><th>Quando</th><th>Tipo</th><th>Valor</th><th>Mensagem</th></tr></thead><tbody>{alert_rows}</tbody></table>" \
                    if alert_rows else "<p class='empty'>Nenhum alerta registrado ainda.</p>"

    labels_j   = json.dumps(charts["labels"])
    cpu_j      = json.dumps(charts["cpu"])
    temp_j     = json.dumps(charts["temp"])
    ram_j      = json.dumps(charts["ram"])

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acer Aspire 5 — Monitor de Sistema</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');
  :root {{
    --bg:#0a0e17;--card:#161e2e;--border:#1f2d45;
    --accent:#00d4ff;--accent2:#ff6b35;--accent3:#a855f7;
    --green:#22c55e;--red:#ef4444;--yellow:#f59e0b;
    --text:#e2e8f0;--muted:#64748b;
    --font:'IBM Plex Sans',sans-serif;--mono:'IBM Plex Mono',monospace;
  }}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}}
  body::before{{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,212,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,212,255,.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}}
  .wrapper{{position:relative;z-index:1;max-width:1400px;margin:0 auto;padding:2rem}}

  header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:2.5rem;padding-bottom:1.5rem;border-bottom:1px solid var(--border)}}
  .brand{{display:flex;align-items:center;gap:1rem}}
  .brand-icon{{width:48px;height:48px;background:linear-gradient(135deg,var(--accent),var(--accent3));border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.4rem}}
  .brand h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.02em}}
  .brand p{{color:var(--muted);font-size:.85rem;margin-top:2px;font-family:var(--mono)}}
  .header-meta{{text-align:right;color:var(--muted);font-size:.8rem;font-family:var(--mono);line-height:1.8}}

  /* Tabs */
  .tabs{{display:flex;gap:.25rem;margin-bottom:1.5rem;border-bottom:1px solid var(--border);padding-bottom:0}}
  .tab{{padding:.6rem 1.25rem;font-size:.82rem;font-weight:600;color:var(--muted);cursor:pointer;border-radius:8px 8px 0 0;border:1px solid transparent;border-bottom:none;transition:.15s}}
  .tab:hover{{color:var(--text);background:rgba(255,255,255,.03)}}
  .tab.active{{color:var(--accent);background:var(--card);border-color:var(--border);border-bottom-color:var(--card);margin-bottom:-1px}}
  .tab-panel{{display:none}}.tab-panel.active{{display:block}}

  .stats-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:2rem}}
  .stat-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.25rem 1.5rem;position:relative;overflow:hidden}}
  .stat-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px}}
  .stat-card.blue::before{{background:var(--accent)}}.stat-card.orange::before{{background:var(--accent2)}}
  .stat-card.purple::before{{background:var(--accent3)}}.stat-card.green::before{{background:var(--green)}}
  .stat-label{{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:.5rem}}
  .stat-value{{font-size:2rem;font-weight:700;font-family:var(--mono);line-height:1}}
  .stat-sub{{font-size:.78rem;color:var(--muted);margin-top:.4rem;font-family:var(--mono)}}
  .stat-card.blue .stat-value{{color:var(--accent)}}.stat-card.orange .stat-value{{color:var(--accent2)}}
  .stat-card.purple .stat-value{{color:var(--accent3)}}.stat-card.green .stat-value{{color:var(--green)}}

  .charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:2rem}}
  .chart-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.5rem}}
  .chart-card.wide{{grid-column:span 2}}
  .chart-title{{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}}
  .chart-dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}

  .tables-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}
  .table-card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.5rem;overflow:hidden}}
  .table-card.wide{{grid-column:span 2}}
  .table-title{{font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:1rem}}

  table{{width:100%;border-collapse:collapse;font-size:.82rem}}
  th{{text-align:left;padding:.5rem .75rem;color:var(--muted);font-weight:400;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}}
  td{{padding:.6rem .75rem;border-bottom:1px solid rgba(31,45,69,.5);font-family:var(--mono);font-size:.78rem}}
  tr:last-child td{{border-bottom:none}}tr:hover td{{background:rgba(0,212,255,.03)}}

  .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.68rem;font-weight:600;letter-spacing:.05em;font-family:var(--font)}}
  .badge.danger{{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}}
  .badge.warn{{background:rgba(245,158,11,.15);color:var(--yellow);border:1px solid rgba(245,158,11,.3)}}
  .badge.ok{{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}}

  .risk-item{{font-size:.75rem;color:var(--yellow);font-family:var(--font)}}
  .mono{{font-family:var(--mono)}}.small{{font-size:.72rem}}
  .muted{{color:var(--muted)}}
  .empty{{color:var(--muted);text-align:center;padding:2rem;font-style:italic}}

  footer{{text-align:center;color:var(--muted);font-size:.75rem;font-family:var(--mono);margin-top:3rem;padding-top:1.5rem;border-top:1px solid var(--border)}}
  @media(max-width:900px){{
    .stats-grid{{grid-template-columns:repeat(2,1fr)}}
    .charts-grid,.tables-grid{{grid-template-columns:1fr}}
    .chart-card.wide,.table-card.wide{{grid-column:span 1}}
  }}
</style>
</head>
<body>
<div class="wrapper">

  <header>
    <div class="brand">
      <div class="brand-icon">🖥️</div>
      <div>
        <h1>Acer Aspire 5 — Monitor</h1>
        <p>crash_pattern_analyzer · sqlite3 · psutil</p>
      </div>
    </div>
    <div class="header-meta">
      <div>Gerado em: {summary['generated_at']}</div>
      <div>Monitoramento: {summary['monitoring_hours']:.1f}h coletadas</div>
      <div>Snapshots: {summary['total_snaps']}</div>
    </div>
  </header>

  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card orange">
      <div class="stat-label">💥 Crashes confirmados</div>
      <div class="stat-value">{summary['crash_count']}</div>
      <div class="stat-sub">detectados no período</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-label">🌡️ Temp CPU máxima</div>
      <div class="stat-value">{summary['max_temp']:.0f}°</div>
      <div class="stat-sub">média: {summary['avg_temp']:.1f}°C</div>
    </div>
    <div class="stat-card purple">
      <div class="stat-label">⚙️ CPU média</div>
      <div class="stat-value">{summary['avg_cpu']:.0f}%</div>
      <div class="stat-sub">uso médio registrado</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">🧠 RAM máxima</div>
      <div class="stat-value">{summary['max_ram']:.0f}%</div>
      <div class="stat-sub">média: {summary['avg_ram']:.1f}%</div>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" onclick="showTab('overview')">Visão Geral</div>
    <div class="tab" onclick="showTab('analysis')">Análise de Crashes</div>
  </div>

  <!-- Tab: Visão Geral -->
  <div id="tab-overview" class="tab-panel active">
    <div class="charts-grid">
      <div class="chart-card wide">
        <div class="chart-title"><span class="chart-dot" style="background:var(--accent2)"></span>Temperatura CPU ao longo do tempo</div>
        <canvas id="tempChart" height="80"></canvas>
      </div>
      <div class="chart-card">
        <div class="chart-title"><span class="chart-dot" style="background:var(--accent)"></span>Uso de CPU %</div>
        <canvas id="cpuChart" height="120"></canvas>
      </div>
      <div class="chart-card">
        <div class="chart-title"><span class="chart-dot" style="background:var(--accent3)"></span>Uso de RAM %</div>
        <canvas id="ramChart" height="120"></canvas>
      </div>
    </div>
    <div class="tables-grid">
      <div class="table-card">
        <div class="table-title">⚡ Histórico de reinicializações</div>
        {boots_table}
      </div>
      <div class="table-card">
        <div class="table-title">⚠️ Alertas recentes</div>
        {alerts_table}
      </div>
    </div>
  </div>

  <!-- Tab: Análise de Crashes -->
  <div id="tab-analysis" class="tab-panel">
    <div class="table-card wide" style="margin-bottom:1rem">
      <div class="table-title">🔍 Métricas nos minutos antes de cada reinicialização</div>
      {analysis_html}
    </div>
  </div>

  <footer>Acer Aspire 5 Crash Monitor · Dados em monitor.db · Rode monitor.py em background</footer>
</div>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}

const labels   = {labels_j};
const cpuData  = {cpu_j};
const tempData = {temp_j};
const ramData  = {ram_j};

const defaults = {{ tension:.3, borderWidth:1.5, pointRadius:0, fill:true }};
const scaleOpts = (min, max) => ({{
  x: {{ ticks:{{color:'#64748b',maxTicksLimit:10}}, grid:{{color:'#1f2d45'}} }},
  y: {{ ticks:{{color:'#64748b'}}, grid:{{color:'#1f2d45'}}, ...(min!=null?{{min}}:{{}}), ...(max!=null?{{max}}:{{}})}},
}});

new Chart(document.getElementById('tempChart'), {{
  type:'line', data:{{ labels, datasets:[{{ ...defaults, label:'Temperatura CPU (°C)', data:tempData, borderColor:'#ff6b35', backgroundColor:'rgba(255,107,53,0.08)' }}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:scaleOpts(30, null) }}
}});
new Chart(document.getElementById('cpuChart'), {{
  type:'line', data:{{ labels, datasets:[{{ ...defaults, label:'CPU %', data:cpuData, borderColor:'#00d4ff', backgroundColor:'rgba(0,212,255,0.07)' }}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:scaleOpts(0, 100) }}
}});
new Chart(document.getElementById('ramChart'), {{
  type:'line', data:{{ labels, datasets:[{{ ...defaults, label:'RAM %', data:ramData, borderColor:'#a855f7', backgroundColor:'rgba(168,85,247,0.07)' }}] }},
  options:{{ responsive:true, plugins:{{legend:{{display:false}}}}, scales:scaleOpts(0, 100) }}
}});
</script>
</body>
</html>"""


# ── main ──────────────────────────────────────────────────────
def main():
    args = parse_args()
    print(f"Carregando dados de {args.db}...")
    snapshots, boots, alerts, stats = load_data(args.db)
    charts, summary, analysis = process_data(snapshots, boots, alerts, stats, args.db, args.window)
    html = render_html(charts, summary, boots, alerts, analysis)
    args.output.write_text(html, encoding="utf-8")
    print(f"Dashboard gerado: {args.output}")
    if not args.no_open:
        webbrowser.open(str(args.output))


if __name__ == "__main__":
    main()