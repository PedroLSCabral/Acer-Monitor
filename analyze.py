#!/usr/bin/env python3
"""
Acer Aspire 5 — Análise de Padrões de Reinicialização
Examina os dados coletados e identifica o que acontecia
nos minutos ANTES de cada reinicialização.

Uso:
    python analyze.py
    python analyze.py --db C:\outro\caminho\monitor.db
    python analyze.py --window 10
    python analyze.py --only-crashes
"""

import sqlite3
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta


def parse_args():
    parser = argparse.ArgumentParser(description="Acer Crash Monitor — Análise de padrões")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent / "monitor.db",
        help="Caminho para o banco de dados (padrão: monitor.db)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=5,
        metavar="MINUTOS",
        help="Janela de análise antes de cada reboot em minutos (padrão: 5)",
    )
    parser.add_argument(
        "--only-crashes",
        action="store_true",
        help="Analisa apenas reinicializações classificadas como crash",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.db.exists():
        print(f"Banco não encontrado: {args.db}")
        print("Rode primeiro: python monitor.py")
        return

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    where = "WHERE notes != 'Primeira execução'"
    if args.only_crashes:
        where = "WHERE kind = 'crash'"

    boots = conn.execute(f"""
        SELECT * FROM boot_events
        {where}
        ORDER BY ts
    """).fetchall()

    if not boots:
        print("Nenhuma reinicialização registrada ainda.")
        print("Continue coletando dados com monitor.py")
        return

    print(f"{'='*60}")
    print(f"  Análise: {len(boots)} reinicializações encontradas")
    print(f"  Janela:  {args.window} minutos antes de cada reboot")
    if args.only_crashes:
        print("  Filtro:  apenas crashes confirmados")
    print(f"{'='*60}\n")

    summaries = []

    for boot in boots:
        last_snap = boot["last_snap_ts"]
        if not last_snap:
            continue

        window_start = (
            datetime.fromisoformat(last_snap) - timedelta(minutes=args.window)
        ).isoformat()

        snaps = conn.execute("""
            SELECT * FROM snapshots
            WHERE ts BETWEEN ? AND ?
            ORDER BY ts
        """, (window_start, last_snap)).fetchall()

        if not snaps:
            continue

        # Calcula métricas da janela
        cpu_vals = [s["cpu_pct"] for s in snaps if s["cpu_pct"]]
        temp_vals = [s["cpu_temp"] for s in snaps if s["cpu_temp"]]
        ram_vals = [s["ram_pct"] for s in snaps if s["ram_pct"]]
        bat_vals = [s["battery_pct"] for s in snaps if s["battery_pct"] is not None]

        summary = {
            "boot_ts": boot["ts"],
            "n_snaps": len(snaps),
            "cpu_avg": sum(cpu_vals)/len(cpu_vals) if cpu_vals else None,
            "cpu_max": max(cpu_vals) if cpu_vals else None,
            "temp_avg": sum(temp_vals)/len(temp_vals) if temp_vals else None,
            "temp_max": max(temp_vals) if temp_vals else None,
            "ram_avg": sum(ram_vals)/len(ram_vals) if ram_vals else None,
            "bat_last": bat_vals[-1] if bat_vals else None,
            "bat_plugged": snaps[-1]["battery_plugged"],
        }
        summaries.append(summary)

        print(f"Reinício em: {boot['ts'][:19]}")
        print(f"  Janela: {args.window} min antes ({len(snaps)} amostras)")
        if summary["cpu_avg"]:
            print(f"  CPU    — média: {summary['cpu_avg']:.1f}%  |  máx: {summary['cpu_max']:.1f}%")
        if summary["temp_avg"]:
            print(f"  Temp   — média: {summary['temp_avg']:.1f}°C |  máx: {summary['temp_max']:.1f}°C")
        if summary["ram_avg"]:
            print(f"  RAM    — média: {summary['ram_avg']:.1f}%")
        if summary["bat_last"] is not None:
            plugged = "na tomada" if summary["bat_plugged"] else "na bateria"
            print(f"  Bateria— {summary['bat_last']:.0f}% ({plugged})")

        # Indicadores de risco
        risks = []
        if summary["temp_max"] and summary["temp_max"] > 85:
            risks.append(f"🌡️  SUPERAQUECIMENTO ({summary['temp_max']:.0f}°C)")
        if summary["cpu_max"] and summary["cpu_max"] > 90:
            risks.append(f"⚙️  CPU SATURADA ({summary['cpu_max']:.0f}%)")
        if summary["ram_avg"] and summary["ram_avg"] > 85:
            risks.append(f"🧠 RAM ALTA ({summary['ram_avg']:.0f}%)")
        if summary["bat_last"] is not None and summary["bat_last"] < 5 and not summary["bat_plugged"]:
            risks.append(f"🔋 BATERIA CRÍTICA ({summary['bat_last']:.0f}%)")

        if risks:
            print(f"  ⚠️  Possíveis causas:")
            for r in risks:
                print(f"     → {r}")
        else:
            print(f"  ❓ Sem indicadores óbvios — pode ser bug de hardware/driver")
        print()

    # Padrão geral
    if summaries:
        print(f"{'='*60}")
        print("  PADRÃO GERAL")
        print(f"{'='*60}")

        all_temps = [s["temp_max"] for s in summaries if s["temp_max"]]
        all_cpus = [s["cpu_max"] for s in summaries if s["cpu_max"]]

        if all_temps:
            print(f"  Temp máxima média antes dos resets: {sum(all_temps)/len(all_temps):.1f}°C")
        if all_cpus:
            print(f"  CPU máxima média antes dos resets:  {sum(all_cpus)/len(all_cpus):.1f}%")

        plugged_count = sum(1 for s in summaries if s["bat_plugged"])
        print(f"  Na tomada:  {plugged_count}/{len(summaries)} reinicializações")
        print(f"  Na bateria: {len(summaries)-plugged_count}/{len(summaries)} reinicializações")

    conn.close()


if __name__ == "__main__":
    main()