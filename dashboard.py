#!/usr/bin/env python3
"""
Acer Aspire 5 — Dashboard de Análise
Gera um relatório HTML a partir do banco de dados.
Uso: python3 dashboard.py
Abre o arquivo dashboard.html no navegador.
"""

import sqlite3
import json
import sys
import webbrowser
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "monitor.db"
OUT_PATH = BASE_DIR / "dashboard.html"


def load_data():
    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        print("Rode primeiro: python3 monitor.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    snapshots = conn.execute("""
        SELECT ts, cpu_pct, cpu_temp, ram_pct, swap_pct,
               battery_pct, battery_plugged,
               proc_count, gpu_temp
        FROM snapshots
        ORDER BY ts DESC
        LIMIT 2000
    """).fetchall()

    boots = conn.execute("""
        SELECT * FROM boot_events ORDER BY ts DESC
    """).fetchall()

    alerts = conn.execute("""
        SELECT * FROM alerts ORDER BY ts DESC LIMIT 100
    """).fetchall()

    stats = conn.execute("""
        SELECT
            COUNT(*) as total_snaps,
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


def generate_html(snapshots, boots, alerts, stats):
    # Prepara séries temporais (ordem cronológica)
    snaps_asc = list(reversed(snapshots))

    labels = json.dumps([s["ts"][11:19] for s in snaps_asc])
    cpu_data = json.dumps([round(s["cpu_pct"] or 0, 1) for s in snaps_asc])
    temp_data = json.dumps([round(s["cpu_temp"] or 0, 1) for s in snaps_asc])
    ram_data = json.dumps([round(s["ram_pct"] or 0, 1) for s in snaps_asc])
    bat_data = json.dumps([round(s["battery_pct"] or 0, 1) for s in snaps_asc])

    boot_rows = ""
    for b in boots:
        badge = '<span class="badge danger">⚡ REINÍCIO</span>' if b["notes"] != "Primeira execução" else '<span class="badge ok">▶ Início</span>'
        boot_rows += f"""
        <tr>
            <td>{b['ts'][:19]}</td>
            <td>{badge}</td>
            <td>{b['boot_time'][:19] if b['boot_time'] else '—'}</td>
            <td class="mono small">{b['last_snap_ts'][:19] if b['last_snap_ts'] else '—'}</td>
        </tr>"""

    alert_rows = ""
    for a in alerts:
        color = "danger" if a["kind"] == "temp" and a["value"] > 85 else "warn"
        alert_rows += f"""
        <tr>
            <td>{a['ts'][:19]}</td>
            <td><span class="badge {color}">{a['kind'].upper()}</span></td>
            <td>{a['value']:.1f}</td>
            <td>{a['message']}</td>
        </tr>"""

    total_boots = len([b for b in boots if b["notes"] != "Primeira execução"])
    monitoring_hours = 0
    if stats and stats["first_ts"] and stats["last_ts"]:
        t1 = datetime.fromisoformat(stats["first_ts"])
        t2 = datetime.fromisoformat(stats["last_ts"])
        monitoring_hours = (t2 - t1).total_seconds() / 3600

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acer Aspire 5 — Monitor de Sistema</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

  :root {{
    --bg: #0a0e17;
    --surface: #111827;
    --card: #161e2e;
    --border: #1f2d45;
    --accent: #00d4ff;
    --accent2: #ff6b35;
    --accent3: #a855f7;
    --green: #22c55e;
    --red: #ef4444;
    --yellow: #f59e0b;
    --text: #e2e8f0;
    --muted: #64748b;
    --font: 'IBM Plex Sans', sans-serif;
    --mono: 'IBM Plex Mono', monospace;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    min-height: 100vh;
  }}

  /* Background grid */
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }}

  .wrapper {{ position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; padding: 2rem; }}

  /* Header */
  header {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 2.5rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
  }}
  .brand {{ display: flex; align-items: center; gap: 1rem; }}
  .brand-icon {{
    width: 48px; height: 48px;
    background: linear-gradient(135deg, var(--accent), var(--accent3));
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.4rem;
  }}
  .brand h1 {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; }}
  .brand p {{ color: var(--muted); font-size: 0.85rem; margin-top: 2px; font-family: var(--mono); }}
  .header-meta {{ text-align: right; color: var(--muted); font-size: 0.8rem; font-family: var(--mono); line-height: 1.8; }}

  /* Stats row */
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
    margin-bottom: 2rem;
  }}
  .stat-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    position: relative;
    overflow: hidden;
  }}
  .stat-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
  }}
  .stat-card.blue::before {{ background: var(--accent); }}
  .stat-card.orange::before {{ background: var(--accent2); }}
  .stat-card.purple::before {{ background: var(--accent3); }}
  .stat-card.green::before {{ background: var(--green); }}
  .stat-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 0.5rem; }}
  .stat-value {{ font-size: 2rem; font-weight: 700; font-family: var(--mono); line-height: 1; }}
  .stat-sub {{ font-size: 0.78rem; color: var(--muted); margin-top: 0.4rem; font-family: var(--mono); }}
  .stat-card.blue .stat-value {{ color: var(--accent); }}
  .stat-card.orange .stat-value {{ color: var(--accent2); }}
  .stat-card.purple .stat-value {{ color: var(--accent3); }}
  .stat-card.green .stat-value {{ color: var(--green); }}

  /* Charts */
  .charts-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 2rem;
  }}
  .chart-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
  }}
  .chart-card.wide {{ grid-column: span 2; }}
  .chart-title {{
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }}
  .chart-dot {{
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
  }}

  /* Tables */
  .tables-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }}
  .table-card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
    overflow: hidden;
  }}
  .table-title {{
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin-bottom: 1rem;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.82rem;
  }}
  th {{
    text-align: left;
    padding: 0.5rem 0.75rem;
    color: var(--muted);
    font-weight: 400;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid rgba(31,45,69,0.5);
    font-family: var(--mono);
    font-size: 0.78rem;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(0,212,255,0.03); }}

  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    font-family: var(--font);
  }}
  .badge.danger {{ background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }}
  .badge.warn {{ background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }}
  .badge.ok {{ background: rgba(34,197,94,0.15); color: var(--green); border: 1px solid rgba(34,197,94,0.3); }}

  .mono {{ font-family: var(--mono); }}
  .small {{ font-size: 0.72rem; }}
  .empty {{ color: var(--muted); text-align: center; padding: 2rem; font-style: italic; }}

  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.75rem;
    font-family: var(--mono);
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
  }}

  @media (max-width: 900px) {{
    .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .charts-grid, .tables-grid {{ grid-template-columns: 1fr; }}
    .chart-card.wide {{ grid-column: span 1; }}
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
      <div>Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</div>
      <div>Monitoramento: {monitoring_hours:.1f}h coletadas</div>
      <div>Snapshots: {stats['total_snaps'] if stats else 0}</div>
    </div>
  </header>

  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card orange">
      <div class="stat-label">⚡ Reinicializações</div>
      <div class="stat-value">{total_boots}</div>
      <div class="stat-sub">detectadas no período</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-label">🌡️ Temp CPU máxima</div>
      <div class="stat-value">{stats['max_temp'] or 0:.0f}°</div>
      <div class="stat-sub">média: {stats['avg_temp'] or 0:.1f}°C</div>
    </div>
    <div class="stat-card purple">
      <div class="stat-label">⚙️ CPU média</div>
      <div class="stat-value">{stats['avg_cpu'] or 0:.0f}%</div>
      <div class="stat-sub">uso médio registrado</div>
    </div>
    <div class="stat-card green">
      <div class="stat-label">🧠 RAM máxima</div>
      <div class="stat-value">{stats['max_ram'] or 0:.0f}%</div>
      <div class="stat-sub">média: {stats['avg_ram'] or 0:.1f}%</div>
    </div>
  </div>

  <!-- Charts -->
  <div class="charts-grid">
    <div class="chart-card wide">
      <div class="chart-title">
        <span class="chart-dot" style="background:var(--accent2)"></span>
        Temperatura CPU ao longo do tempo (últimas 2000 amostras)
      </div>
      <canvas id="tempChart" height="80"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">
        <span class="chart-dot" style="background:var(--accent)"></span>
        Uso de CPU %
      </div>
      <canvas id="cpuChart" height="120"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-title">
        <span class="chart-dot" style="background:var(--accent3)"></span>
        Uso de RAM %
      </div>
      <canvas id="ramChart" height="120"></canvas>
    </div>
  </div>

  <!-- Tables -->
  <div class="tables-grid">
    <div class="table-card">
      <div class="table-title">⚡ Histórico de reinicializações</div>
      {"<p class='empty'>Nenhuma reinicialização registrada ainda.</p>" if not boot_rows else f"<table><thead><tr><th>Quando</th><th>Tipo</th><th>Boot em</th><th>Último snap</th></tr></thead><tbody>{boot_rows}</tbody></table>"}
    </div>
    <div class="table-card">
      <div class="table-title">⚠️ Alertas recentes</div>
      {"<p class='empty'>Nenhum alerta registrado ainda.</p>" if not alert_rows else f"<table><thead><tr><th>Quando</th><th>Tipo</th><th>Valor</th><th>Mensagem</th></tr></thead><tbody>{alert_rows}</tbody></table>"}
    </div>
  </div>

  <footer>
    Acer Aspire 5 Crash Monitor · Dados em monitor.db · Rode monitor.py em background
  </footer>
</div>

<script>
const labels = {labels};
const cpuData = {cpu_data};
const tempData = {temp_data};
const ramData = {ram_data};

const chartDefaults = {{
  tension: 0.3,
  borderWidth: 1.5,
  pointRadius: 0,
  fill: true,
}};

// Temp
new Chart(document.getElementById('tempChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      ...chartDefaults,
      label: 'Temperatura CPU (°C)',
      data: tempData,
      borderColor: '#ff6b35',
      backgroundColor: 'rgba(255,107,53,0.08)',
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 10 }}, grid: {{ color: '#1f2d45' }} }},
      y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1f2d45' }}, suggestedMin: 30 }}
    }}
  }}
}});

// CPU
new Chart(document.getElementById('cpuChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      ...chartDefaults,
      label: 'CPU %',
      data: cpuData,
      borderColor: '#00d4ff',
      backgroundColor: 'rgba(0,212,255,0.07)',
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 8 }}, grid: {{ color: '#1f2d45' }} }},
      y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1f2d45' }}, min: 0, max: 100 }}
    }}
  }}
}});

// RAM
new Chart(document.getElementById('ramChart'), {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      ...chartDefaults,
      label: 'RAM %',
      data: ramData,
      borderColor: '#a855f7',
      backgroundColor: 'rgba(168,85,247,0.07)',
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 8 }}, grid: {{ color: '#1f2d45' }} }},
      y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1f2d45' }}, min: 0, max: 100 }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def main():
    print(f"Carregando dados de {DB_PATH}...")
    snapshots, boots, alerts, stats = load_data()
    html = generate_html(snapshots, boots, alerts, stats)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard gerado: {OUT_PATH}")
    webbrowser.open(str(OUT_PATH))


if __name__ == "__main__":
    main()